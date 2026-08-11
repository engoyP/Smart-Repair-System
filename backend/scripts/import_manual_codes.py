"""设备手册错误码导入脚本 - 从设备说明书导入"错误码 → 故障诊断"条目到 PostgreSQL + Milvus

数据边界约定（重要）：
- 本表（manual_code_entries / log_code 集合）**只接受设备说明书/维修手册**中的错误码条目，
  含章节/页码用于出处回溯；不接收工单数据。
- 涉及错误码的维修工单照常沉淀到知识库（knowledge_items），检索时双库并行召回再融合。

使用方式:
    cd backend
    python scripts/import_manual_codes.py

前提条件:
    - PostgreSQL 已启动，数据库已迁移（alembic upgrade head，含 manual_code_entries 表）
    - Milvus 已启动（log_code 集合不存在时会自动创建）
"""
import sys
import os

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.core.database import SessionLocal
from app.models.manual_code import ManualCodeEntry
from app.core.vector_store import log_code_store
from app.core.embeddings import encode_text


# ==================== 设备说明书错误码示例数据 ====================
# 说明：真实场景下这些数据来自设备说明书"错误码表"章节的解析（Excel/CSV/PDF 抽取），
# 此处按说明书原文格式构造示例，用于打通全链路。
SEED_MANUAL_CODES = [
    # ==================== FANUC Series 0i 数控系统维修手册 ====================
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "SV0436",
        "title": "伺服放大器过电流报警",
        "description": "伺服放大器检测到输出电流超过额定值，伺服电机停止运行，系统显示 SV0436 报警。",
        "causes": "1）伺服电机动力线绝缘破损导致相间短路；2）电机抱闸未完全打开，启动瞬间电流过大；3）机械负载过大（导轨润滑不良或传动卡死）。",
        "solutions": "a. 用兆欧表测量电机三相绕组对地绝缘（应>100MΩ）；b. 检查抱闸电源（DC24V）及抱闸线圈电阻（正常40±5Ω）；c. 检查导轨润滑泵油位及油路是否堵塞；d. 断开联轴器手转丝杠，确认机械部分无卡死。",
        "chapter": "6.2 伺服报警（SV）",
        "page": "P245",
    },
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "PS0002",
        "title": "系统电池电压低报警",
        "description": "CNC 控制器后备电池（3.6V 锂电池）电压低于 3.0V，系统显示 PS0002 电池报警，存在参数丢失风险。",
        "causes": "后备电池电压耗尽（正常寿命约 1 年）或电池回路接触不良。",
        "solutions": "a. 确认机床已断电；b. 打开控制柜找到电池盒（FANUC 通常在主板上）；c. 在通电状态下热更换电池，防止参数丢失；d. 更换后核对系统参数完整性；e. 建议每 12 个月定期更换一次。",
        "chapter": "5.4 系统报警（PS）",
        "page": "P198",
    },
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "SV0401",
        "title": "伺服位置偏差过大报警",
        "description": "伺服轴实际位置与指令位置的偏差超过系统设定值（参数 1829），系统显示 SV0401 报警并停止该轴。",
        "causes": "1）机械负载过大导致堵转；2）伺服电机或编码器连接异常；3）加减速时间常数设定过小；4）丝杠/导轨卡滞。",
        "solutions": "a. 查看诊断号 DGN800 定位偏差值；b. 检查机械传动部分是否卡滞；c. 检查电机动力线和编码器线缆插头；d. 适当加大加减速时间常数（参数 1620）；e. 确认制动器已释放。",
        "chapter": "6.3 伺服报警（SV）",
        "page": "P252",
    },
    {
        "manual_name": "FANUC Series 0i 数控系统维修手册",
        "device_type": "数控机床",
        "error_code": "EX1006",
        "title": "主轴放大器温度过高报警",
        "description": "主轴驱动器散热器温度超过 85°C，触发 EX1006 过热报警，主轴停止旋转。",
        "causes": "1）控制柜通风散热不良；2）主轴长时间重载切削；3）主轴风扇损坏；4）环境温度过高。",
        "solutions": "a. 检查控制柜风扇及过滤网，清理灰尘；b. 检查主轴电机风扇是否运转；c. 降低切削负载或增加间歇；d. 改善控制柜散热（加装空调或风机）；e. 确认环境温度<40°C。",
        "chapter": "6.5 主轴报警（EX）",
        "page": "P260",
    },

    # ==================== KUKA KR210 机械臂维修手册 ====================
    {
        "manual_name": "KUKA KR210 机械臂维修手册",
        "device_type": "机器人",
        "error_code": "6401",
        "title": "电机温度监控报警",
        "description": "KRC 控制器检测到某轴伺服电机温度传感器超过报警阈值（>100°C），该轴停止运行，示教器显示 6401 报警。",
        "causes": "1）电机持续重载或堵转；2）电机散热风扇故障；3）环境温度过高；4）电机抱闸未释放导致持续摩擦发热。",
        "solutions": "a. 在示教器查看报警轴号；b. 检查该轴电机风扇与散热片积灰；c. 手动盘动该轴确认无卡滞；d. 检查抱闸电源（DC24V）是否正常释放；e. 降低节拍或负载，观察温度曲线。",
        "chapter": "8.1 驱动器报警",
        "page": "P312",
    },
    {
        "manual_name": "KUKA KR210 机械臂维修手册",
        "device_type": "机器人",
        "error_code": "6500",
        "title": "供电电压过低报警",
        "description": "KRC 控制器监测到主供电电压低于额定值 15% 以上，系统进入保护性停机并显示 6500 报警。",
        "causes": "1）车间电网电压波动；2）变压器容量不足；3）接线端子松动接触电阻增大；4）三相不平衡。",
        "solutions": "a. 用万用表测量控制柜输入端三相电压（应 380V±10%）；b. 检查进线端子紧固力矩；c. 测量三相电压不平衡度（应<3%）；d. 确认稳压器/变压器容量匹配；e. 检查配电柜空开与电缆规格。",
        "chapter": "8.2 驱动器报警",
        "page": "P318",
    },
    {
        "manual_name": "KUKA KR210 机械臂维修手册",
        "device_type": "机器人",
        "error_code": "R0910",
        "title": "安全区域监控错误报警",
        "description": "机器人运行轨迹超出设定的安全区域监控范围，触发 R0910 报警，机器人急停。",
        "causes": "1）工作程序轨迹修改后安全区域未重新定义；2）安全区域参数（$CFG_CPR）被意外修改；3）机械原点丢失导致坐标偏移。",
        "solutions": "a. 在 WORKVISUAL 中重新定义安全区域；b. 核对 $CFG_CPR 区域参数与现场一致；c. 执行轴零点标定（Mastering）恢复坐标；d. 确认防护栏/光栅状态正常后复位急停。",
        "chapter": "9 安全系统",
        "page": "P340",
    },

    # ==================== 西门子 SIMATIC 维修手册 ====================
    {
        "manual_name": "西门子 SIMATIC S7-300 系统手册",
        "device_type": "PLC系统",
        "error_code": "E3091",
        "title": "PROFIBUS DP 从站通信中断报警",
        "description": "DP 主站与从站通信超时，总线系统进入安全状态，故障单元停止运行，CPU 显示 E3091（总线故障代码）。",
        "causes": "1）总线连接器/终端电阻接触不良或未设置；2）通信电缆破损或受强电干扰；3）从站掉电或模块故障；4）波特率设置不一致。",
        "solutions": "a. 检查总线连接器（DB9）与终端电阻拨码；b. 用 BT200 诊断适配器逐段检测总线；c. 检查从站电源与 DP 接口模块；d. 核对主从站波特率一致（推荐 1.5Mbps）；e. 通信线远离动力电缆并良好接地。",
        "chapter": "12.3 PROFIBUS 故障诊断",
        "page": "P198",
    },
]


# ==================== 导入逻辑 ====================

def import_manual_codes():
    """主导入函数"""
    logger.info(f"开始导入 {len(SEED_MANUAL_CODES)} 条设备手册错误码条目...")

    db = SessionLocal()
    inserted_count = 0
    vector_count = 0
    skipped_count = 0
    errors = []

    try:
        for i, item in enumerate(SEED_MANUAL_CODES):
            try:
                # 判重：同一手册 + 同一错误码只导入一次
                existing = db.query(ManualCodeEntry).filter(
                    ManualCodeEntry.manual_name == item["manual_name"],
                    ManualCodeEntry.error_code == item["error_code"],
                ).first()
                if existing:
                    skipped_count += 1
                    logger.info(f"  已存在，跳过: {item['manual_name']} / {item['error_code']}")
                    continue

                # 1. 写入 PostgreSQL
                entry = ManualCodeEntry(
                    manual_name=item["manual_name"],
                    device_type=item.get("device_type"),
                    error_code=item["error_code"],
                    title=item["title"],
                    description=item["description"],
                    causes=item.get("causes", ""),
                    solutions=item.get("solutions", ""),
                    chapter=item.get("chapter", ""),
                    page=item.get("page", ""),
                    version=1,
                )
                db.add(entry)
                db.flush()  # 获得 entry.id

                # 2. 写入 Milvus log_code 集合（对 title + description 编码）
                text_for_embedding = f"{item['title']} {item['description']}"
                vector = encode_text(text_for_embedding)

                point_id = log_code_store.insert(
                    vector=vector,
                    manual_code_id=entry.id,
                    error_code=item["error_code"],
                    manual_name=item["manual_name"],
                    device_type=item.get("device_type"),
                    title=item["title"],
                    description=item["description"],
                    chapter=item.get("chapter", ""),
                    page=item.get("page", ""),
                )

                # 更新 milvus_id 关联
                entry.milvus_id = point_id
                db.flush()
                inserted_count += 1
                vector_count += 1

                if (i + 1) % 5 == 0:
                    db.commit()
                    logger.info(f"  已处理: {i + 1}/{len(SEED_MANUAL_CODES)}")

            except Exception as e:
                errors.append(f"第 {i+1} 条 '{item.get('error_code', '')} - {item.get('title', '')[:20]}' 失败: {e}")
                logger.warning(f"  第 {i+1} 条失败: {e}")
                db.rollback()

        # 最终提交
        db.commit()

        # 批量向量插入完成后统一刷写
        if vector_count > 0:
            log_code_store.flush()
            logger.info("log_code 向量数据已刷写落盘")

        logger.info(f"导入完成: 成功 {inserted_count} 条, 跳过 {skipped_count} 条, 失败 {len(errors)} 条")
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
    import_manual_codes()
