from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.models.user import User
from app.models.work_order import WorkOrder
from app.schemas import (
    KnowledgeCreate, KnowledgeUpdate, KnowledgeResponse, PaginatedResponse,
    KnowledgeExtractRequest, KnowledgeExtractResponse, KnowledgeDedupResult,
    KnowledgeReviewRequest, KnowledgeReviewResponse,
)
from app.agents.knowledge_extractor import knowledge_extractor

router = APIRouter()


def _k_to_dict(k: KnowledgeItem) -> dict:
    return {c.name: getattr(k, c.name) for c in k.__table__.columns}


# ==================== CRUD ====================

@router.get("/", response_model=PaginatedResponse[KnowledgeResponse], summary="获取知识条目列表")
def list_knowledge_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    device_type: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(KnowledgeItem)
    if status:
        query = query.filter(KnowledgeItem.status == status)
    if device_type:
        query = query.filter(KnowledgeItem.device_type == device_type)
    if keyword:
        query = query.filter(
            KnowledgeItem.title.ilike(f"%{keyword}%")
            | KnowledgeItem.content.ilike(f"%{keyword}%")
        )
    total = query.count()
    items = query.order_by(KnowledgeItem.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_k_to_dict(k) for k in items], "page": page, "page_size": page_size}


@router.get("/{knowledge_id}", response_model=KnowledgeResponse, summary="获取知识条目详情")
def get_knowledge_item(knowledge_id: int, db: Session = Depends(get_db)):
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == knowledge_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    return item


@router.post("/", response_model=KnowledgeResponse, summary="创建知识条目")
def create_knowledge_item(data: KnowledgeCreate, db: Session = Depends(get_db)):
    item = KnowledgeItem(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{knowledge_id}", response_model=KnowledgeResponse, summary="更新知识条目（只读禁止）")
def update_knowledge_item(knowledge_id: int, data: KnowledgeUpdate, db: Session = Depends(get_db)):
    """知识库为只读，禁止修改已收录的知识条目（防止污染检索依据）"""
    raise HTTPException(status_code=403, detail="知识库为只读，禁止修改知识条目")


@router.delete("/{knowledge_id}", summary="删除知识条目（只读禁止）")
def delete_knowledge_item(knowledge_id: int, db: Session = Depends(get_db)):
    """知识库为只读，禁止删除已收录的知识条目"""
    raise HTTPException(status_code=403, detail="知识库为只读，禁止删除知识条目")


# ==================== 语义检索 ====================

@router.get("/search", summary="语义检索知识条目")
def search_knowledge(
    query: str = Query(..., description="检索关键词"),
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    limit: int = 5,
    db: Session = Depends(get_db)
):
    try:
        from app.core.vector_store import vector_store
        from app.core.embeddings import encode_text
        query_vec = encode_text(query)
        results = vector_store.search(
            query_vector=query_vec,
            limit=limit,
            device_type=device_type,
            fault_code=fault_code,
            score_threshold=0.3,
        )
        return {"query": query, "device_type": device_type, "fault_code": fault_code, "results": results}
    except Exception as e:
        return {"query": query, "results": [], "error": str(e)}


# ==================== 从工单提取知识 ====================

@router.post("/extract", response_model=KnowledgeExtractResponse, summary="从工单提取知识条目")
def extract_from_work_order(req: KnowledgeExtractRequest, db: Session = Depends(get_db)):
    """
    从已审批工单中提取知识条目：
    1. LLM 提取结构化知识
    2. 向量去重检测
    3. 无重复 → 自动创建 DRAFT 条目
    4. 有重复 → 返回匹配条目，不自动创建
    """
    wo = db.query(WorkOrder).filter(WorkOrder.id == req.work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")

    # 1. 组装工单数据
    analysis = wo.analysis_result if isinstance(wo.analysis_result, dict) else {}
    wo_data = {
        "fault_description": wo.fault_description,
        "fault_code": wo.fault_code,
        "fault_phenomenon": wo.fault_phenomenon,
        "root_cause": wo.root_cause,
        "solution_steps": wo.solution_steps,
        "device_type": analysis.get("device_type", ""),
        "tags": wo.tags or [],
    }

    # 2. LLM 提取
    extracted = knowledge_extractor.extract(wo_data)
    if not extracted.title:
        raise HTTPException(status_code=500, detail="知识提取失败：无法从工单中提取有效内容")

    # 3. 去重检测
    dedup = _check_duplicate(extracted, db)

    # 4. 决策
    if dedup.has_duplicate:
        return KnowledgeExtractResponse(
            extracted=_extracted_to_dict(extracted),
            dedup=dedup,
            knowledge_id=None,
            auto_created=False,
        )

    # 5. 无重复 → 自动创建
    knowledge = KnowledgeItem(
        title=extracted.title,
        content=extracted.content,
        device_type=extracted.device_type,
        fault_code=extracted.fault_code,
        fault_tags=extracted.fault_tags,
        source_type="WORK_ORDER",
        source_id=wo.id,
        status=KnowledgeStatus.DRAFT,
        extraction_meta={
            "work_order_no": wo.work_order_no,
            "dedup_score": dedup.similarity_score,
            "keywords": extracted.keywords,
        },
    )
    db.add(knowledge)
    db.commit()
    db.refresh(knowledge)

    logger.info(f"[Knowledge] 从工单 {wo.work_order_no} 自动提取知识: #{knowledge.id} {knowledge.title[:30]}...")

    return KnowledgeExtractResponse(
        extracted=_extracted_to_dict(extracted),
        dedup=dedup,
        knowledge_id=knowledge.id,
        auto_created=True,
    )


# ==================== 审核流程 ====================

@router.post("/{knowledge_id}/review", response_model=KnowledgeReviewResponse, summary="知识审核")
def review_knowledge(
    knowledge_id: int,
    review: KnowledgeReviewRequest,
    db: Session = Depends(get_db),
):
    """
    知识审核操作：
    - submit: 提交审核 (DRAFT → UNDER_REVIEW)
    - publish: 审核通过发布 (UNDER_REVIEW → PUBLISHED)，同步向量到 Milvus
    - reject: 驳回 (UNDER_REVIEW → DRAFT)，附带修改建议
    - deprecate: 标记过期 (PUBLISHED → DEPRECATED)
    """
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == knowledge_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")

    action_map = {
        "submit": (KnowledgeStatus.UNDER_REVIEW, [KnowledgeStatus.DRAFT]),
        "publish": (KnowledgeStatus.PUBLISHED, [KnowledgeStatus.UNDER_REVIEW]),
        "reject": (KnowledgeStatus.DRAFT, [KnowledgeStatus.UNDER_REVIEW]),
        "deprecate": (KnowledgeStatus.DEPRECATED, [KnowledgeStatus.PUBLISHED]),
    }

    if review.action not in action_map:
        raise HTTPException(status_code=400, detail=f"不支持的审核操作: {review.action}")

    new_status, allowed_from = action_map[review.action]
    if item.status not in allowed_from:
        raise HTTPException(
            status_code=400,
            detail=f"无法从 {item.status.value} 执行 {review.action}，仅允许 {[s.value for s in allowed_from]} 状态"
        )

    item.status = new_status
    if review.comment:
        item.review_comment = review.comment

    # 发布时同步向量到 Milvus
    if review.action == "publish":
        try:
            _sync_to_milvus(item, db)
        except Exception as e:
            logger.error(f"[Knowledge] 向量同步失败: {e}")
            item.status = KnowledgeStatus.DRAFT  # 回滚状态
            db.commit()
            raise HTTPException(status_code=500, detail=f"向量同步失败: {str(e)}")

    db.commit()
    db.refresh(item)

    logger.info(f"[Knowledge] #{item.id} {item.title[:30]}... {review.action} -> {new_status.value}")
    return KnowledgeReviewResponse(
        knowledge_id=item.id,
        new_status=new_status.value,
        action=review.action,
        comment=review.comment,
    )


# ==================== 手动去重检测 ====================

@router.post("/{knowledge_id}/check-duplicate", response_model=KnowledgeDedupResult, summary="检测重复知识")
def check_duplicate(knowledge_id: int, db: Session = Depends(get_db)):
    """对已有知识条目执行去重检测"""
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == knowledge_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="知识条目不存在")

    from app.agents.knowledge_extractor import ExtractedKnowledge
    pseudo = ExtractedKnowledge(
        title=item.title,
        content=item.content,
        device_type=item.device_type or "",
        fault_code=item.fault_code or "",
        fault_tags=item.fault_tags or [],
        keywords=[item.title, item.fault_code or ""],
    )
    return _check_duplicate(pseudo, db, exclude_id=item.id)


# ==================== 内部函数 ====================

def _extracted_to_dict(extracted) -> dict:
    return {
        "title": extracted.title,
        "content": extracted.content,
        "fault_code": extracted.fault_code,
        "device_type": extracted.device_type,
        "fault_tags": extracted.fault_tags,
        "keywords": extracted.keywords,
    }


def _check_duplicate(extracted, db: Session, exclude_id: Optional[int] = None) -> KnowledgeDedupResult:
    """
    去重检测：故障码快速匹配 + 向量语义检索 + DedupAgent LLM 判定

    维修场景下，同设备同故障码可能有不同原因和方案，不能仅凭标题相似度判定重复。
    流程：
    1. 故障码+设备类型精确匹配 → 若命中，直接调用 DedupAgent
    2. 向量检索找到候选条目（阈值 0.55）
    3. 对相似度 >= 0.65 的候选，调用 DedupAgent 对比原因和方案
    4. Agent 判定为真重复 → 跳过；判定为相似案例 → 正常收录
    """
    has_dup = False
    max_score = 0.0
    matched = []

    new_item = {
        "title": extracted.title,
        "content": extracted.content,
        "device_type": extracted.device_type,
        "fault_code": extracted.fault_code,
    }

    # 0. 快速路径：故障码精确匹配（忽略设备类型，因为"PLC"vs"PLC系统"vs"PLC电源模块"视为同一类）
    if extracted.fault_code:
        try:
            # 解析故障码（支持逗号分隔的多个故障码）
            from sqlalchemy import or_
            codes = [c.strip() for c in extracted.fault_code.split(',') if c.strip()]
            if codes:
                # 用 OR+LIKE 匹配每个故障码，支持已有条目中存储多个故障码的情况
                exact_query = db.query(KnowledgeItem).filter(
                    KnowledgeItem.status.in_([
                        KnowledgeStatus.PUBLISHED, KnowledgeStatus.UNDER_REVIEW, KnowledgeStatus.DRAFT
                    ]),
                )
                # 排除自身
                if exclude_id:
                    exact_query = exact_query.filter(KnowledgeItem.id != exclude_id)
                # 每个故障码单独做 LIKE 匹配，因为已有条目可能也存多个
                code_conditions = []
                for code in codes:
                    code_conditions.append(KnowledgeItem.fault_code.like(f"%{code}%"))
                exact_query = exact_query.filter(or_(*code_conditions))

            exact_matches = exact_query.order_by(KnowledgeItem.id.desc()).limit(5).all()
            for em in exact_matches:
                if extracted.content and em.content:
                    from app.agents.dedup_agent import dedup_agent
                    decision = dedup_agent.check(
                        new_item=new_item,
                        existing_item={
                            "title": em.title,
                            "content": em.content or "",
                            "device_type": em.device_type or "",
                            "fault_code": em.fault_code or "",
                        },
                        title_similarity=0.85,
                    )
                    is_true_dup = decision.is_duplicate
                    if is_true_dup:
                        has_dup = True
                        max_score = max(max_score, 0.85)
                        matched.append({
                            "knowledge_id": em.id,
                            "title": em.title,
                            "similarity": 0.85,
                            "content_preview": (em.content or "")[:100],
                            "match_type": "fault_code_exact",
                            "is_true_duplicate": True,
                            "dedup_reason": decision.reason,
                        })
                        logger.info(
                            f"[DedupAgent] 故障码精确匹配命中: "
                            f"fault_code={extracted.fault_code} → {em.title[:40]} "
                            f"reason={decision.reason[:80]}"
                        )
        except Exception as e:
            logger.warning(f"[Knowledge] 故障码快速去重检测失败: {e}")

    # 1. 向量语义检索找相似候选
    if not has_dup:
        try:
            from app.core.embeddings import encode_text
            from app.core.vector_store import vector_store

            # 构建查询文本：用内容前200字也加入查询，增强语义匹配
            content_snippet = (extracted.content or "")[:200]
            query_text = f"{extracted.device_type or ''} {extracted.title} {extracted.fault_code or ''} {' '.join(extracted.keywords[:3])} {content_snippet}"
            query_vec = encode_text(query_text)
            results = vector_store.search(
                query_vector=query_vec,
                limit=8,
                device_type=extracted.device_type if extracted.device_type else None,
                score_threshold=0.45,
            )

            for r in results:
                kid = r.get("knowledge_id")
                if kid and kid == exclude_id:
                    continue

                title_sim = r["score"]
                max_score = max(max_score, title_sim)

                is_true_dup = False
                dedup_reason = ""
                if title_sim >= 0.55 and extracted.content:
                    existing_content = r.get("content", "") or ""
                    if existing_content:
                        from app.agents.dedup_agent import dedup_agent
                        decision = dedup_agent.check(
                            new_item=new_item,
                            existing_item={
                                "title": r.get("title", ""),
                                "content": existing_content,
                                "device_type": r.get("device_type", ""),
                                "fault_code": r.get("fault_code", ""),
                            },
                            title_similarity=title_sim,
                        )
                        is_true_dup = decision.is_duplicate
                        dedup_reason = decision.reason
                        logger.info(
                            f"[DedupAgent] title_sim={title_sim:.2f} "
                            f"is_duplicate={is_true_dup} confidence={decision.confidence:.2f} "
                            f"reason={decision.reason[:80]}"
                        )

                if is_true_dup:
                    has_dup = True

                matched.append({
                    "knowledge_id": kid,
                    "title": r.get("title", ""),
                    "similarity": round(title_sim, 3),
                    "content_preview": (r.get("content", "") or "")[:100],
                    "is_true_duplicate": is_true_dup,
                    "dedup_reason": dedup_reason,
                })
        except Exception as e:
            logger.warning(f"[Knowledge] 向量去重检测失败: {e}")

    # 2. 标题关键词模糊匹配（补充检测）
    if not has_dup and extracted.title:
        keywords = [k for k in extracted.keywords if len(k) >= 3]
        if keywords:
            query = db.query(KnowledgeItem).filter(KnowledgeItem.status.in_([
                KnowledgeStatus.PUBLISHED, KnowledgeStatus.UNDER_REVIEW, KnowledgeStatus.DRAFT
            ]))
            if exclude_id:
                query = query.filter(KnowledgeItem.id != exclude_id)
            for kw in keywords[:3]:
                query = query.filter(KnowledgeItem.title.ilike(f"%{kw}%"))
            existing = query.first()
            if existing:
                is_true_dup = False
                dedup_reason = ""
                if extracted.content and existing.content:
                    from app.agents.dedup_agent import dedup_agent
                    decision = dedup_agent.check(
                        new_item=new_item,
                        existing_item={
                            "title": existing.title,
                            "content": existing.content or "",
                            "device_type": existing.device_type or "",
                            "fault_code": existing.fault_code or "",
                        },
                        title_similarity=0.75,
                    )
                    is_true_dup = decision.is_duplicate
                    dedup_reason = decision.reason

                score = 0.75
                max_score = max(max_score, score)
                matched.append({
                    "knowledge_id": existing.id,
                    "title": existing.title,
                    "similarity": score,
                    "content_preview": (existing.content or "")[:100],
                    "match_type": "keyword",
                    "is_true_duplicate": is_true_dup,
                    "dedup_reason": dedup_reason,
                })
                if is_true_dup:
                    has_dup = True

    # 3. 内容关键词模糊匹配（最终补漏：在内容中搜索关键词）
    if not has_dup and extracted.content:
        keywords = [k for k in extracted.keywords if len(k) >= 2]
        if keywords:
            query = db.query(KnowledgeItem).filter(KnowledgeItem.status.in_([
                KnowledgeStatus.PUBLISHED, KnowledgeStatus.UNDER_REVIEW, KnowledgeStatus.DRAFT
            ]))
            if exclude_id:
                query = query.filter(KnowledgeItem.id != exclude_id)
            # 在 content 或 title 中匹配关键词
            from sqlalchemy import or_
            content_conditions = []
            for kw in keywords[:5]:
                content_conditions.append(KnowledgeItem.content.ilike(f"%{kw}%"))
                content_conditions.append(KnowledgeItem.title.ilike(f"%{kw}%"))
            existing = query.filter(or_(*content_conditions)).order_by(KnowledgeItem.id.desc()).first()
            if existing and existing.id != exclude_id:
                is_true_dup = False
                dedup_reason = ""
                if extracted.content and existing.content:
                    from app.agents.dedup_agent import dedup_agent
                    decision = dedup_agent.check(
                        new_item=new_item,
                        existing_item={
                            "title": existing.title,
                            "content": existing.content or "",
                            "device_type": existing.device_type or "",
                            "fault_code": existing.fault_code or "",
                        },
                        title_similarity=0.55,
                    )
                    is_true_dup = decision.is_duplicate
                    dedup_reason = decision.reason

                score = 0.55
                max_score = max(max_score, score)
                matched.append({
                    "knowledge_id": existing.id,
                    "title": existing.title,
                    "similarity": score,
                    "content_preview": (existing.content or "")[:100],
                    "match_type": "content_keyword",
                    "is_true_duplicate": is_true_dup,
                    "dedup_reason": dedup_reason,
                })
                if is_true_dup:
                    has_dup = True

    return KnowledgeDedupResult(
        has_duplicate=has_dup,
        similarity_score=round(max_score, 3),
        matched_items=matched,
    )


def _sync_to_milvus(item: KnowledgeItem, db: Session):
    """将知识条目向量化并同步到 Milvus"""
    from app.core.embeddings import encode_text
    from app.core.vector_store import vector_store

    text = f"{item.title} {item.content[:2000]}"
    vec = encode_text(text)

    if item.milvus_id:
        # 更新已有向量
        vector_store.update(
            point_id=item.milvus_id,
            vector=vec,
            title=item.title,
            content=item.content,
            device_type=item.device_type,
            fault_code=item.fault_code,
            fault_tags=item.fault_tags,
        )
    else:
        # 插入新向量
        point_id = vector_store.insert(
            vector=vec,
            knowledge_id=item.id,
            title=item.title,
            content=item.content,
            device_type=item.device_type,
            fault_code=item.fault_code,
            fault_tags=item.fault_tags,
        )
        item.milvus_id = point_id

    logger.info(f"[Knowledge] 向量同步成功: #{item.id} milvus_id={item.milvus_id}")


# ==================== 知识库引用查询 ====================

@router.get("/solutions", summary="查询处理步骤（供工单引用）")
def query_solutions(
    keyword: str = Query(..., description="搜索关键词"),
    device_type: Optional[str] = Query(None),
    top_k: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """
    根据关键词和设备类型搜索知识库中的处理步骤。
    返回匹配条目的 title + solution_steps，供维修员在工单中选择引用。
    """
    from sqlalchemy import or_

    q = db.query(KnowledgeItem).filter(
        KnowledgeItem.status == "PUBLISHED",
        KnowledgeItem.solution_steps.isnot(None),
        KnowledgeItem.solution_steps != "",
    )

    kw_pattern = f"%{keyword}%"
    q = q.filter(
        or_(
            KnowledgeItem.title.like(kw_pattern),
            KnowledgeItem.content.like(kw_pattern),
            KnowledgeItem.fault_code.like(kw_pattern),
            KnowledgeItem.device_type.like(kw_pattern),
        )
    )

    if device_type:
        q = q.filter(KnowledgeItem.device_type == device_type)

    items = q.order_by(KnowledgeItem.id.desc()).limit(top_k).all()

    results = []
    for item in items:
        # 提取 solution_steps 中的步骤列表
        solutions = [s.strip() for s in (item.solution_steps or "").split("\n") if s.strip()]
        results.append({
            "knowledge_id": item.id,
            "title": item.title,
            "fault_code": item.fault_code,
            "device_type": item.device_type,
            "solution_steps": item.solution_steps,
            "solution_count": len(solutions),
        })

    return {"total": len(results), "results": results}
