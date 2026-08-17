"""设备手册错误码导入脚本 - 从设备说明书导入"错误码 → 故障诊断"条目到 PostgreSQL + Milvus

数据边界约定（重要）：
- 本表（manual_code_entries / log_code 集合）**只接受设备说明书/维修手册**中的错误码条目，
  含章节/页码用于出处回溯；不接收工单数据。
- 涉及错误码的维修工单照常沉淀到知识库（knowledge_items），检索时双库并行召回再融合。

结构化（2026-08-14）：条目按"情形"组织（conditions），新增 message_text/severity/effect/related_codes；
causes/solutions 为 deprecated 过渡列，不再写入。

使用方式:
    cd backend
    python scripts/import_manual_codes.py                          # 种子数据增量导入（同码 upsert）
    python scripts/import_manual_codes.py --json-file manual_codes.json   # 从 JSON 文件导入
    python scripts/import_manual_codes.py --force-rebuild          # 清空重灌（换模型迁移用）
    python scripts/import_manual_codes.py --force-rebuild --target-collection log_code_bgem3
    python scripts/import_manual_codes.py --resync                 # 按 PG 重灌全部向量（修复 Milvus 不一致）

前提条件:
    - 推理服务已启动（bge-m3 编码走 HTTP）：start_all.ps1 或 python -m app.core.embedding_server
    - PostgreSQL 已启动，数据库已迁移（alembic upgrade head，含 manual_code_entries 表）
    - Milvus 已启动（log_code 集合不存在时会自动创建）
"""
import sys
import os
import json
import argparse
from typing import Optional

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.manual_code import ManualCodeEntry
from app.core.vector_store import log_code_store, LogCodeVectorStore
from app.core.embeddings import encode_text, is_server_available
from app.core.manual_text import normalize_error_code, build_manual_embedding_text


def check_inference_server():
    """推理服务连通性检查（服务化后，向量脚本必须先启动推理服务）"""
    if not is_server_available():
        logger.error(f"推理服务不可用: {settings.EMBEDDING_SERVER_URL}")
        logger.error("请先启动推理服务：start_all.ps1 或 python -m app.core.embedding_server")
        sys.exit(1)


# ==================== 设备说明书错误码示例数据 ====================
# 说明：真实场景下这些数据来自设备说明书"错误码表"章节的解析（Excel/CSV/PDF 抽取），
# 此处按说明书原文格式构造示例，用于打通全链路。
# 字段说明：conditions = [{signal 日志可观察信号, cause 原因, steps 处理步骤}]；
# severity = EX急停 / OH停机 / INFO提示；effect = 急停 / 停机 / 仅提示。
SEED_MANUAL_CODES = [
    # ==================== FANUC Series 0i 数控系统维修手册 ====================
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "SV0436",
        "title": "伺服放大器过电流报警",
        "message_text": "SV0436 X AXIS: EXCESS CURRENT IN SERVO",
        "description": "伺服放大器检测到输出电流超过额定值，伺服电机停止运行，系统显示 SV0436 报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0401"],
        "conditions": [
            {
                "signal": "上电或启动瞬间报警，伴随电机异响或火花",
                "cause": "伺服电机动力线绝缘破损导致相间短路",
                "steps": "a. 用兆欧表测量电机三相绕组对地绝缘（应>100MΩ）；b. 检查动力线外观有无破损、拖链内有无挤压",
            },
            {
                "signal": "启动瞬间电流突增报警，电机无法转动",
                "cause": "电机抱闸未完全打开，启动瞬间电流过大",
                "steps": "a. 检查抱闸电源（DC24V）及抱闸线圈电阻（正常40±5Ω）；b. 确认抱闸释放时序正确",
            },
            {
                "signal": "重载加工中报警",
                "cause": "机械负载过大（导轨润滑不良或传动卡死）",
                "steps": "a. 检查导轨润滑泵油位及油路是否堵塞；b. 断开联轴器手转丝杠，确认机械部分无卡死",
            },
        ],
        "chapter": "6.2 伺服报警（SV）",
        "page": "P245",
    },
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "PS0002",
        "title": "系统电池电压低报警",
        "message_text": "PS0002 BATTERY VOLTAGE ZERO",
        "description": "CNC 控制器后备电池（3.6V 锂电池）电压低于 3.0V，系统显示 PS0002 电池报警，存在参数丢失风险。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "开机显示 PS0002，机床各轴功能正常",
                "cause": "后备电池电压耗尽（正常寿命约 1 年）或电池回路接触不良",
                "steps": "a. 确认机床已断电；b. 打开控制柜找到电池盒（FANUC 通常在主板上）；c. 在通电状态下热更换电池，防止参数丢失；d. 更换后核对系统参数完整性；e. 建议每 12 个月定期更换一次",
            },
        ],
        "chapter": "5.4 系统报警（PS）",
        "page": "P198",
    },
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "SV0401",
        "title": "伺服位置偏差过大报警",
        "message_text": "SV0401 X AXIS: EXCESS ERROR",
        "description": "伺服轴实际位置与指令位置的偏差超过系统设定值（参数 1829），系统显示 SV0401 报警并停止该轴。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0436"],
        "conditions": [
            {
                "signal": "加工中突发报警且伴随异响",
                "cause": "机械负载过大导致堵转",
                "steps": "a. 查看诊断号 DGN800 定位偏差值；b. 检查机械传动部分是否卡滞",
            },
            {
                "signal": "报警伴随编码器/反馈异常提示",
                "cause": "伺服电机或编码器连接异常",
                "steps": "a. 检查电机动力线和编码器线缆插头；b. 检查线缆屏蔽层接地",
            },
            {
                "signal": "频繁加减速时报警",
                "cause": "加减速时间常数设定过小",
                "steps": "a. 适当加大加减速时间常数（参数 1620）；b. 观察 DGN800 偏差值变化",
            },
            {
                "signal": "停机保持时位置漂移报警",
                "cause": "制动器未释放或丝杠/导轨卡滞",
                "steps": "a. 确认制动器已释放；b. 检查丝杠/导轨润滑与卡滞",
            },
        ],
        "chapter": "6.3 伺服报警（SV）",
        "page": "P252",
    },
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "EX1006",
        "title": "主轴放大器温度过高报警",
        "message_text": "EX1006 SPINDLE AMPLIFIER OVERHEAT",
        "description": "主轴驱动器散热器温度超过 85°C，触发 EX1006 过热报警，主轴停止旋转。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "长时间重载切削后报警",
                "cause": "主轴长时间重载切削",
                "steps": "a. 降低切削负载或增加间歇；b. 观察散热器温度恢复情况",
            },
            {
                "signal": "开机不久即报警或温度快速上升",
                "cause": "控制柜通风散热不良或主轴风扇损坏",
                "steps": "a. 检查控制柜风扇及过滤网，清理灰尘；b. 检查主轴电机风扇是否运转",
            },
            {
                "signal": "夏季高温时段报警",
                "cause": "环境温度过高",
                "steps": "a. 改善控制柜散热（加装空调或风机）；b. 确认环境温度<40°C",
            },
        ],
        "chapter": "6.5 主轴报警（EX）",
        "page": "P260",
    },

    # ==================== KUKA KR210 机械臂维修手册 ====================
    {
        "manual_name": "KUKA KR210 机械臂维修手册",
        "device_type": "机器人",
        "error_code": "6401",
        "title": "电机温度监控报警",
        "message_text": "6401 Motor temperature monitoring - axis exceeded",
        "description": "KRC 控制器检测到某轴伺服电机温度传感器超过报警阈值（>100°C），该轴停止运行，示教器显示 6401 报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "重载/高速运行中报警",
                "cause": "电机持续重载或堵转",
                "steps": "a. 在示教器查看报警轴号；b. 手动盘动该轴确认无卡滞；c. 降低节拍或负载，观察温度曲线",
            },
            {
                "signal": "报警伴随风扇异常噪声或停转",
                "cause": "电机散热风扇故障",
                "steps": "a. 检查该轴电机风扇与散热片积灰；b. 更换损坏风扇",
            },
            {
                "signal": "停机后仍温度报警或启动即报",
                "cause": "电机抱闸未释放导致持续摩擦发热",
                "steps": "a. 检查抱闸电源（DC24V）是否正常释放；b. 检查抱闸线圈电阻",
            },
        ],
        "chapter": "8.1 驱动器报警",
        "page": "P312",
    },
    {
        "manual_name": "KUKA KR210 机械臂维修手册",
        "device_type": "机器人",
        "error_code": "6500",
        "title": "供电电压过低报警",
        "message_text": "6500 Undervoltage main supply",
        "description": "KRC 控制器监测到主供电电压低于额定值 15% 以上，系统进入保护性停机并显示 6500 报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "车间用电高峰时段报警",
                "cause": "车间电网电压波动或变压器容量不足",
                "steps": "a. 用万用表测量控制柜输入端三相电压（应 380V±10%）；b. 确认稳压器/变压器容量匹配",
            },
            {
                "signal": "报警伴随端子发热或异味",
                "cause": "接线端子松动接触电阻增大",
                "steps": "a. 检查进线端子紧固力矩；b. 检查端子有无氧化变色",
            },
            {
                "signal": "特定相电压偏低报警",
                "cause": "三相不平衡",
                "steps": "a. 测量三相电压不平衡度（应<3%）；b. 检查配电柜空开与电缆规格",
            },
        ],
        "chapter": "8.2 驱动器报警",
        "page": "P318",
    },
    {
        "manual_name": "KUKA KR210 机械臂维修手册",
        "device_type": "机器人",
        "error_code": "R0910",
        "title": "安全区域监控错误报警",
        "message_text": "R0910 Workspace monitoring exceeded",
        "description": "机器人运行轨迹超出设定的安全区域监控范围，触发 R0910 报警，机器人急停。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "程序轨迹修改后首次运行报警",
                "cause": "工作程序轨迹修改后安全区域未重新定义",
                "steps": "a. 在 WORKVISUAL 中重新定义安全区域；b. 空运行验证轨迹在区域内",
            },
            {
                "signal": "参数未改动情况下突然报警",
                "cause": "安全区域参数（$CFG_CPR）被意外修改",
                "steps": "a. 核对 $CFG_CPR 区域参数与现场一致；b. 确认防护栏/光栅状态正常后复位急停",
            },
            {
                "signal": "报警伴随坐标偏移或位置偏差",
                "cause": "机械原点丢失导致坐标偏移",
                "steps": "a. 执行轴零点标定（Mastering）恢复坐标；b. 重新核对安全区域边界",
            },
        ],
        "chapter": "9 安全系统",
        "page": "P340",
    },

    # ==================== 西门子 SIMATIC 维修手册 ====================
    {
        "manual_name": "西门子 SIMATIC S7-300 系统手册",
        "device_type": "PLC系统",
        "error_code": "E3091",
        "title": "PROFIBUS DP 从站通信中断报警",
        "message_text": "E3091 Bus fault DP slave communication interrupted",
        "description": "DP 主站与从站通信超时，总线系统进入安全状态，故障单元停止运行，CPU 显示 E3091（总线故障代码）。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "报警伴随从站电源指示灯灭",
                "cause": "从站掉电或模块故障",
                "steps": "a. 检查从站电源与 DP 接口模块；b. 更换故障模块",
            },
            {
                "signal": "通信时断时续或间歇报警",
                "cause": "总线连接器/终端电阻接触不良或未设置",
                "steps": "a. 检查总线连接器（DB9）与终端电阻拨码；b. 重新插紧连接器",
            },
            {
                "signal": "附近大功率设备启动时报警",
                "cause": "通信电缆破损或受强电干扰",
                "steps": "a. 用 BT200 诊断适配器逐段检测总线；b. 通信线远离动力电缆并良好接地",
            },
            {
                "signal": "组态后首次通信报警",
                "cause": "波特率设置不一致",
                "steps": "a. 核对主从站波特率一致（推荐 1.5Mbps）；b. 重新下载组态",
            },
        ],
        "chapter": "12.3 PROFIBUS 故障诊断",
        "page": "P198",
    },
]


# ==================== 导入逻辑 ====================

def _normalize_item(item: dict) -> dict:
    """导入条目归一化（error_code 大写、manual_name 去空白、字段默认值）"""
    out = dict(item)
    out["error_code"] = normalize_error_code(item.get("error_code", ""))
    out["manual_name"] = (item.get("manual_name") or "").strip()
    out["message_text"] = item.get("message_text") or ""
    out["severity"] = (item.get("severity") or "").upper()
    if out["severity"] not in ("EX", "OH", "INFO"):
        out["severity"] = None
    out["effect"] = item.get("effect") or ""
    out["conditions"] = item.get("conditions") or []
    out["related_codes"] = item.get("related_codes") or []
    return out


def _write_entry(db, store, item: dict, existing: Optional[ManualCodeEntry] = None) -> str:
    """写入 PG（新建或更新）+ 重编码写入 Milvus，返回 ('created'|'updated')"""
    if existing is not None:
        # upsert：全字段更新 + Milvus 删旧插新
        for k in ("manual_name", "device_type", "error_code", "title", "description",
                  "message_text", "severity", "effect", "conditions", "related_codes",
                  "chapter", "page"):
            if k in item:
                setattr(existing, k, item[k])
        old_milvus_id = existing.milvus_id
        entry = existing
    else:
        entry = ManualCodeEntry(**{k: item.get(k) for k in (
            "manual_name", "device_type", "error_code", "title", "description",
            "message_text", "severity", "effect", "conditions", "related_codes",
            "chapter", "page")})
        db.add(entry)
        old_milvus_id = None
    db.flush()  # 获得 entry.id

    # 向量化：结构化锚点（error_code + title + message_text + description + 前3情形信号）
    vector = encode_text(build_manual_embedding_text(item))
    point_id = store.insert(
        vector=vector,
        manual_code_id=entry.id,
        error_code=item["error_code"],
        manual_name=item["manual_name"],
        device_type=item.get("device_type"),
        title=item["title"],
        description=item["description"],
        chapter=item.get("chapter") or "",
        page=item.get("page") or "",
    )
    if old_milvus_id:
        store.delete(old_milvus_id)
    entry.milvus_id = point_id
    db.flush()
    return "updated" if existing is not None else "created"


def import_manual_codes(
    force_rebuild: bool = False,
    target_collection: str = "",
    json_file: str = "",
    resync: bool = False,
):
    """主导入函数

    Args:
        force_rebuild: 清空 manual_code_entries 表 + 目标 Milvus 集合后重灌（换模型迁移用）
        target_collection: 目标 Milvus 集合名（默认 settings.MILVUS_LOG_CODE_COLLECTION）
        json_file: JSON 文件路径（数组格式，字段见 manual_codes.example.json）；缺省用种子数据
        resync: 只按 PG 重灌全部向量（PG 不动，修复 Milvus 不一致，如 PUT 中途失败）
    """
    check_inference_server()
    store = (LogCodeVectorStore(collection_name=target_collection)
             if target_collection else log_code_store)
    store_name = target_collection or settings.MILVUS_LOG_CODE_COLLECTION

    # 数据源：--json-file 优先，否则种子数据
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            raw_items = json.load(f)
        if not isinstance(raw_items, list):
            logger.error(f"--json-file 内容必须是数组: {json_file}")
            sys.exit(1)
        items = [_normalize_item(it) for it in raw_items if isinstance(it, dict)]
    else:
        items = [_normalize_item(it) for it in SEED_MANUAL_CODES]

    db = SessionLocal()
    created_count = 0
    updated_count = 0
    vector_count = 0
    errors = []

    try:
        if force_rebuild:
            # 清空 PG 手册表 + 目标集合（旧向量一并清除，避免残留/重复）
            cleared = db.query(ManualCodeEntry).delete()
            db.commit()
            logger.info(f"force-rebuild: 已清空 manual_code_entries 表（{cleared} 条）")
            store.drop_collection()
            # drop 后原 Collection 对象已失效，重建实例以便后续自动建集合
            store = LogCodeVectorStore(collection_name=store_name)

        if resync:
            # 只修 Milvus：按 PG 全部条目重编码删旧插新
            rows = db.query(ManualCodeEntry).all()
            logger.info(f"--resync: 按 PG 重灌 {len(rows)} 条手册向量...")
            for i, row in enumerate(rows):
                try:
                    item = {c.name: getattr(row, c.name) for c in row.__table__.columns}
                    item = _normalize_item(item)
                    old_milvus_id = row.milvus_id
                    vector = encode_text(build_manual_embedding_text(item))
                    point_id = store.insert(
                        vector=vector,
                        manual_code_id=row.id,
                        error_code=item["error_code"],
                        manual_name=item["manual_name"],
                        device_type=item.get("device_type"),
                        title=item["title"],
                        description=item["description"],
                        chapter=item.get("chapter") or "",
                        page=item.get("page") or "",
                    )
                    if old_milvus_id:
                        store.delete(old_milvus_id)
                    row.milvus_id = point_id
                    db.flush()
                    vector_count += 1
                    if (i + 1) % 5 == 0:
                        db.commit()
                except Exception as e:
                    errors.append(f"resync 第 {i+1} 条 '{row.error_code}' 失败: {e}")
                    db.rollback()
            db.commit()
            if vector_count:
                store.flush()
            logger.info(f"resync 完成: 重灌 {vector_count} 条, 失败 {len(errors)} 条")
            if errors:
                logger.warning(f"失败清单:\n" + "\n".join(errors[:10]))
            return

        logger.info(f"开始导入 {len(items)} 条设备手册错误码条目 -> 集合 {store_name} ...")
        for i, item in enumerate(items):
            try:
                # upsert：同一手册 + 同一错误码 → 更新（重跑脚本即数据升级路径）
                existing = db.query(ManualCodeEntry).filter(
                    ManualCodeEntry.manual_name == item["manual_name"],
                    ManualCodeEntry.error_code == item["error_code"],
                ).first()
                action = _write_entry(db, store, item, existing)
                if action == "created":
                    created_count += 1
                else:
                    updated_count += 1
                vector_count += 1

                if (i + 1) % 5 == 0:
                    db.commit()
                    logger.info(f"  已处理: {i + 1}/{len(items)}")

            except Exception as e:
                errors.append(f"第 {i+1} 条 '{item.get('error_code', '')} - {item.get('title', '')[:20]}' 失败: {e}")
                logger.warning(f"  第 {i+1} 条失败: {e}")
                db.rollback()

        # 最终提交
        db.commit()

        # 批量向量插入完成后统一刷写
        if vector_count > 0:
            store.flush()
            logger.info(f"{store_name} 向量数据已刷写落盘")

        logger.info(f"导入完成: 新建 {created_count} 条, 更新 {updated_count} 条, 失败 {len(errors)} 条")
        logger.info(f"向量化: {vector_count} 条")

        if errors:
            logger.warning(f"失败清单:\n" + "\n".join(errors[:10]))

    except Exception as e:
        db.rollback()
        logger.error(f"导入过程异常终止: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="设备手册错误码导入（PostgreSQL + Milvus log_code 集合）")
    parser.add_argument("--force-rebuild", action="store_true",
                        help="清空 manual_code_entries 表与目标集合后重灌（换模型迁移用）")
    parser.add_argument("--target-collection", default="",
                        help="目标 Milvus 集合名（默认 settings.MILVUS_LOG_CODE_COLLECTION；无损迁移时指定新集合）")
    parser.add_argument("--json-file", default="",
                        help="JSON 文件路径（数组格式，字段见 scripts/manual_codes.example.json）；缺省用种子数据")
    parser.add_argument("--resync", action="store_true",
                        help="只按 PG 重灌全部向量（PG 不动，修复 Milvus 不一致）")
    args = parser.parse_args()
    import_manual_codes(
        force_rebuild=args.force_rebuild,
        target_collection=args.target_collection,
        json_file=args.json_file,
        resync=args.resync,
    )
