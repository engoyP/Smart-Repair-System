"""基于测试数据方案生成 500 条工业场景测试数据

执行前会清空所有已有数据（设备、工单、知识库、备件）。
"""
import random
import uuid
from datetime import datetime, date, timedelta
from sqlalchemy import text
from app.core.database import SessionLocal
from app.models.device import Device
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.models.spare_part import SparePart
from app.models.user import User, UserRole

random.seed(42)

# ==================== 配置 ====================
DEVICE_TYPES = ['注塑机', '空压机', '数控机床', '输送设备', 'PLC系统']
TYPE_WEIGHTS = [0.3, 0.2, 0.2, 0.15, 0.15]

MANUFACTURERS = {
    '注塑机': ['海天', '震雄', '伊之密'],
    '空压机': ['阿特拉斯·科普柯', '复盛', '寿力'],
    '数控机床': ['发那科', '西门子', '三菱'],
    '输送设备': ['三一重工', '中联重科', '徐工'],
    'PLC系统': ['三菱', '西门子', '欧姆龙'],
}

MODELS = {
    '注塑机': ['天润ME系列', '天锐VE系列', '天翔SA系列'],
    '空压机': ['GA系列', 'GHS系列', 'LPG系列'],
    '数控机床': ['0i系列', '840D系列', 'M80系列'],
    '输送设备': ['B系列', 'SC系列', 'RB系列'],
    'PLC系统': ['FX系列', 'S7系列', 'Q系列'],
}

REMARKS = {
    '注塑机': [
        '伺服节能型，适用于精密注塑件生产',
        '液压传动，适用于大型注塑件加工',
        '全电动型，高速高精度，适合电子行业',
    ],
    '空压机': [
        '永磁变频空压机，排气压力0.8MPa',
        '工频空压机，适用于持续供气场景',
        '无油空压机，适用于精密设备供气',
    ],
    '数控机床': [
        '五轴联动加工中心，适用于复杂曲面加工',
        '车铣复合，适用于精密轴类零件',
        '立式加工中心，适用于模具加工',
    ],
    '输送设备': [
        '皮带输送线，适用于散料输送',
        '链板输送线，适用于重型工件输送',
        '滚筒输送线，适用于箱体类物料',
    ],
    'PLC系统': [
        '中大型PLC控制系统，适用于产线自动化',
        '分布式I/O系统，适用于远程站点控制',
        '运动控制器，适用于多轴联动控制',
    ],
}

# 故障模板：设备类型 -> 故障列表
FAULT_TEMPLATES = {
    '注塑机': [
        {
            'fault_code': 'FC-001',
            'fault_description': '电机异响',
            'fault_phenomenon': '运行时有周期性异响，伴有振动加剧，噪音值>85dB',
            'root_cause': '电机轴承磨损，滚道疲劳剥落，润滑脂劣化',
            'solution_steps': '1. 停机断电，拆卸电机端盖\n2. 检查轴承间隙，径向跳动>0.03mm则需更换\n3. 更换SKF-BRG-6205轴承\n4. 添加SHC 625专用润滑脂至填充量1/3\n5. 重新组装并测试运行平稳性',
            'used_parts': [{'name': 'SKF-BRG-6205轴承', 'qty': 1}, {'name': 'SHC 625润滑脂', 'qty': 0.5}],
            'tags': ['电机', '轴承', '异响'],
        },
        {
            'fault_code': 'FC-002',
            'fault_description': '液压系统压力波动',
            'fault_phenomenon': '压力表指针剧烈摆动，注射量不稳定，产品重量偏差>3%',
            'root_cause': '液压阀芯磨损，密封圈老化，油液污染',
            'solution_steps': '1. 停机泄压，拆卸液压阀体\n2. 清洁阀芯和阀座\n3. 更换磨损密封件\n4. 更换液压油过滤器\n5. 重新调试系统压力',
            'used_parts': [{'name': '液压阀密封件组套', 'qty': 1}, {'name': '液压油过滤器', 'qty': 1}],
            'tags': ['液压', '压力波动', '密封件'],
        },
        {
            'fault_code': 'FC-003',
            'fault_description': '射胶量不稳定',
            'fault_phenomenon': '实际射胶量与设定值偏差>5%，产品重量波动大',
            'root_cause': '螺杆磨损，止逆环失效，背压阀故障',
            'solution_steps': '1. 拆卸螺杆组件检查\n2. 测量螺杆外径磨损量\n3. 更换止逆环和密封环\n4. 校准背压阀设定值\n5. 重新进行射胶量测试',
            'used_parts': [{'name': '止逆环组件', 'qty': 1}, {'name': '螺杆密封环', 'qty': 2}],
            'tags': ['射胶', '螺杆', '背压'],
        },
        {
            'fault_code': 'FC-004',
            'fault_description': '模具温度失控',
            'fault_phenomenon': '模温机显示温度与实际偏差>10℃，产品缩水率异常',
            'root_cause': '模温机加热管烧毁，温度传感器失效，冷却水路堵塞',
            'solution_steps': '1. 检查模温机加热管电阻\n2. 更换损坏的加热管\n3. 清洁或更换温度传感器\n4. 反向冲洗冷却水路\n5. 重新校准温控参数',
            'used_parts': [{'name': '模温机加热管', 'qty': 2}, {'name': '温度传感器PT100', 'qty': 1}],
            'tags': ['模具', '温度', '传感器'],
        },
        {
            'fault_code': 'FC-005',
            'fault_description': '开合模异响',
            'fault_phenomenon': '开合模过程中有金属撞击声，模板平行度超差',
            'root_cause': '格林柱磨损，调模机构间隙过大，润滑不足',
            'solution_steps': '1. 检查格林柱表面磨损\n2. 测量模板平行度\n3. 调整调模螺母间隙\n4. 加注润滑脂至格林柱油杯\n5. 低速开合模测试',
            'used_parts': [{'name': '格林柱润滑组件', 'qty': 1}],
            'tags': ['开合模', '格林柱', '润滑'],
        },
    ],
    '空压机': [
        {
            'fault_code': 'E01',
            'fault_description': '排气温度过高报警',
            'fault_phenomenon': '排气温度持续>110℃，触发高温报警停机',
            'root_cause': '冷却器翅片堵塞，空气滤清器压差>50mbar，环境温度>40℃',
            'solution_steps': '1. 停机泄压\n2. 使用压缩空气清洁冷却器翅片\n3. 更换空气滤清器滤芯\n4. 检查机房通风\n5. 补充ISO 68抗磨液压油至标准油位',
            'used_parts': [{'name': '空气滤清器滤芯', 'qty': 1}, {'name': 'ISO 68液压油', 'qty': 5}],
            'tags': ['冷却', '排气温度', '滤芯'],
        },
        {
            'fault_code': 'E03',
            'fault_description': '电机过载保护',
            'fault_phenomenon': '电机电流>额定值15%，过载保护器动作停机',
            'root_cause': '电机轴承卡滞，散热风扇损坏，负载过大',
            'solution_steps': '1. 检查电机负载电流\n2. 清洁电机散热片和风扇\n3. 检查电机轴承状态\n4. 测量绝缘电阻\n5. 复位过载保护器后试运行',
            'used_parts': [{'name': '电机散热风扇', 'qty': 1}],
            'tags': ['电机', '过载', '散热'],
        },
        {
            'fault_code': 'E08',
            'fault_description': '冷却器堵塞',
            'fault_phenomenon': '冷却效果下降，油温>90℃，排气温度偏高',
            'root_cause': '冷却器内部结垢，翅片间粉尘堆积',
            'solution_steps': '1. 拆卸冷却器端盖\n2. 使用专用清洗剂循环清洗\n3. 压缩空气吹干\n4. 检查冷却风扇运转\n5. 重新装配后测试',
            'used_parts': [{'name': '冷却器密封垫', 'qty': 2}, {'name': '冷却器清洗剂', 'qty': 2}],
            'tags': ['冷却器', '堵塞', '清洗'],
        },
        {
            'fault_code': 'E05',
            'fault_description': '油压过低报警',
            'fault_phenomenon': '润滑油压力<0.15MPa，触发低油压报警',
            'root_cause': '油位过低，油泵滤网堵塞，油压调节阀故障',
            'solution_steps': '1. 检查油位，补充ISO 68液压油\n2. 拆卸清洗油泵进口滤网\n3. 检查油压调节阀\n4. 更换油分离器芯\n5. 测试油压恢复至0.2-0.3MPa',
            'used_parts': [{'name': '油分离器芯', 'qty': 1}, {'name': '油泵滤网', 'qty': 1}],
            'tags': ['油压', '润滑', '滤网'],
        },
        {
            'fault_code': 'E04',
            'fault_description': '相序错误报警',
            'fault_phenomenon': '启动时报相序错误，电机反转',
            'root_cause': '供电线路相序接反，相序保护器故障',
            'solution_steps': '1. 使用相序表检测进线相序\n2. 调整任意两相线序\n3. 检查相序保护器指示灯\n4. 重新启动测试',
            'used_parts': [],
            'tags': ['电气', '相序', '供电'],
        },
    ],
    '数控机床': [
        {
            'fault_code': 'FC-101',
            'fault_description': '主轴过热报警',
            'fault_phenomenon': '主轴温度>65℃，加工表面出现振纹',
            'root_cause': '主轴轴承预紧力不当，润滑不良，冷却系统故障',
            'solution_steps': '1. 检查主轴冷却液流量\n2. 测量主轴轴承温度\n3. 检查主轴润滑脂状态\n4. 清洁冷却管路\n5. 调整主轴参数降速运行',
            'used_parts': [{'name': '主轴轴承7014C', 'qty': 2}],
            'tags': ['主轴', '过热', '轴承'],
        },
        {
            'fault_code': 'FC-102',
            'fault_description': 'X轴过载报警',
            'fault_phenomenon': 'X轴移动时力矩过大，伺服驱动器报警',
            'root_cause': '导轨润滑不足，丝杠轴承损坏，防护罩变形摩擦',
            'solution_steps': '1. 检查导轨润滑状态\n2. 手动盘动丝杠检查阻力\n3. 检查防护罩是否卡阻\n4. 更换丝杠轴承\n5. 重新润滑并测试',
            'used_parts': [{'name': '丝杠轴承组', 'qty': 1}, {'name': '导轨润滑脂', 'qty': 1}],
            'tags': ['X轴', '过载', '导轨'],
        },
        {
            'fault_code': 'FC-103',
            'fault_description': '加工精度超差',
            'fault_phenomenon': '零件尺寸偏差>0.05mm，重复定位精度>0.02mm',
            'root_cause': '反向间隙过大，主轴热漂移，刀具磨损',
            'solution_steps': '1. 测量反向间隙\n2. 执行螺距误差补偿\n3. 检测主轴热变形量\n4. 更换磨损刀具\n5. 重新校准坐标系',
            'used_parts': [{'name': '刀具组件', 'qty': 1}],
            'tags': ['精度', '补偿', '校准'],
        },
        {
            'fault_code': 'FC-104',
            'fault_description': '换刀故障',
            'fault_phenomenon': '刀库换刀时卡刀，刀套无法正常翻转',
            'root_cause': '刀库定位销磨损，液压/气压不足，凸轮机构卡滞',
            'solution_steps': '1. 检查刀库定位销磨损\n2. 测量气源压力>0.6MPa\n3. 润滑凸轮机构\n4. 手动盘动刀库测试\n5. 重新执行换刀程序',
            'used_parts': [{'name': '刀库定位销', 'qty': 2}],
            'tags': ['换刀', '刀库', '卡刀'],
        },
        {
            'fault_code': 'FC-105',
            'fault_description': '系统死机/黑屏',
            'fault_phenomenon': '数控系统运行时突然死机，屏幕无显示或蓝屏',
            'root_cause': '电源模块故障，主板电容老化，散热风扇停转',
            'solution_steps': '1. 检查24V电源模块输出电压\n2. 清洁主板灰尘\n3. 更换散热风扇\n4. 检查CF卡/硬盘连接\n5. 重新启动并执行系统自检',
            'used_parts': [{'name': '系统散热风扇', 'qty': 1}],
            'tags': ['系统', '死机', '电源'],
        },
    ],
    '输送设备': [
        {
            'fault_code': 'FC-301',
            'fault_description': '皮带打滑',
            'fault_phenomenon': '输送带与驱动滚筒相对滑动，线速度下降>10%',
            'root_cause': '皮带张力不足，滚筒表面磨损，物料堆积过载',
            'solution_steps': '1. 调整张紧装置增加张力\n2. 检查滚筒包胶磨损\n3. 清除滚筒表面粘附物\n4. 清理输送带下方积料\n5. 测试空载和负载运行',
            'used_parts': [{'name': '滚筒包胶层', 'qty': 1}],
            'tags': ['皮带', '打滑', '张紧'],
        },
        {
            'fault_code': 'FC-302',
            'fault_description': '托辊卡死',
            'fault_phenomenon': '输送带运行阻力增大，多处托辊不转动',
            'root_cause': '托辊轴承进水锈蚀，润滑脂干涸，密封损坏',
            'solution_steps': '1. 逐个检查托辊转动情况\n2. 拆卸卡死托辊\n3. 更换同型号轴承\n4. 重新加注润滑脂\n5. 安装并调整对中',
            'used_parts': [{'name': '托辊轴承6204', 'qty': 4}],
            'tags': ['托辊', '卡死', '轴承'],
        },
        {
            'fault_code': 'FC-303',
            'fault_description': '跑偏报警',
            'fault_phenomenon': '输送带向一侧偏移>50mm，触发跑偏开关报警',
            'root_cause': '滚筒安装偏斜，物料落料点偏载，机架变形',
            'solution_steps': '1. 测量滚筒水平度\n2. 调整调心托辊\n3. 调整落料导料槽位置\n4. 校正机架水平\n5. 空载运行观察跑偏',
            'used_parts': [],
            'tags': ['跑偏', '调心', '滚筒'],
        },
        {
            'fault_code': 'FC-304',
            'fault_description': '电机过热停机',
            'fault_phenomenon': '驱动电机外壳温度>80℃，热保护动作',
            'root_cause': '负载过大，散热不良，电压不平衡>3%',
            'solution_steps': '1. 测量三相电流平衡\n2. 检查电机散热风扇\n3. 清洁电机外壳灰尘\n4. 减轻输送负载\n5. 测试空载电流',
            'used_parts': [{'name': '电机散热风扇罩', 'qty': 1}],
            'tags': ['电机', '过热', '负载'],
        },
        {
            'fault_code': 'FC-305',
            'fault_description': '减速箱漏油',
            'fault_phenomenon': '减速箱输入/输出轴处有油液渗漏，油位下降',
            'root_cause': '油封老化磨损，箱体密封面松动，通气塞堵塞',
            'solution_steps': '1. 清洁漏油区域\n2. 更换输入轴油封\n3. 更换输出轴油封\n4. 拧紧箱体螺栓\n5. 补充齿轮油至标准油位',
            'used_parts': [{'name': '输入轴油封', 'qty': 1}, {'name': '输出轴油封', 'qty': 1}, {'name': '齿轮油', 'qty': 3}],
            'tags': ['减速箱', '漏油', '油封'],
        },
    ],
    'PLC系统': [
        {
            'fault_code': '6101',
            'fault_description': 'RAM错误',
            'fault_phenomenon': 'PLC报RAM错误代码，程序丢失，系统无法启动',
            'root_cause': '电池电压过低，RAM芯片老化，电源波动',
            'solution_steps': '1. 更换PLC后备电池\n2. 重新下载备份程序\n3. 检查24V电源稳定性\n4. 执行内存初始化\n5. 重启PLC并监控',
            'used_parts': [{'name': 'PLC后备电池', 'qty': 1}],
            'tags': ['PLC', 'RAM', '电池'],
        },
        {
            'fault_code': '6201',
            'fault_description': '通信故障',
            'fault_phenomenon': 'PLC与上位机通信中断，数据采集停止',
            'root_cause': '通信电缆破损，接口松动，通信模块故障',
            'solution_steps': '1. 检查通信电缆连接\n2. 测量通信线电阻\n3. 更换损坏网线/DP线\n4. 重启通信模块\n5. 重新建立连接',
            'used_parts': [{'name': '通信电缆', 'qty': 1}],
            'tags': ['通信', '网络', '模块'],
        },
        {
            'fault_code': '6300',
            'fault_description': '程序错误',
            'fault_phenomenon': 'PLC运行中报程序语法错误，输出异常',
            'root_cause': '程序逻辑错误，I/O地址冲突，运算溢出',
            'solution_steps': '1. 使用编程软件在线监控\n2. 定位错误程序段\n3. 修正逻辑错误\n4. 重新编译下载\n5. 测试各功能正常',
            'used_parts': [],
            'tags': ['程序', '逻辑', '调试'],
        },
        {
            'fault_code': '6401',
            'fault_description': '电源异常',
            'fault_phenomenon': 'PLC电源指示灯不亮，模块不工作',
            'root_cause': '电源模块保险丝熔断，输入电压超出范围',
            'solution_steps': '1. 测量输入电压\n2. 检查电源模块保险丝\n3. 更换电源模块\n4. 检查后端负载是否短路\n5. 上电测试',
            'used_parts': [{'name': 'PLC电源模块', 'qty': 1}, {'name': '保险丝', 'qty': 2}],
            'tags': ['电源', '模块', '保险丝'],
        },
        {
            'fault_code': '6501',
            'fault_description': 'I/O模块故障',
            'fault_phenomenon': '特定输入/输出通道无响应，指示灯异常',
            'root_cause': 'I/O模块光耦损坏，接线端子松动，模块烧毁',
            'solution_steps': '1. 检查对应通道接线\n2. 万用表测量输入信号\n3. 更换损坏的I/O模块\n4. 重新接线确认\n5. 测试通道通断',
            'used_parts': [{'name': 'I/O模块', 'qty': 1}],
            'tags': ['I/O', '模块', '通道'],
        },
    ],
}

# 备件规格映射
PART_SPECS = {
    'SKF-BRG-6205轴承': '尺寸25×52×15mm，精度等级P0',
    'SHC 625润滑脂': '1kg/桶，耐高温200°C',
    '液压阀密封件组套': '含O型圈6种规格各5个',
    '液压油过滤器': '过滤精度10μm，流量100L/min',
    '止逆环组件': '材质SKD11，硬度HRC58-62',
    '螺杆密封环': 'PTFE材质，耐温300°C',
    '模温机加热管': '功率9kW，电压380V',
    '温度传感器PT100': '测温范围-50~200°C，精度A级',
    '格林柱润滑组件': '含油杯和润滑油管',
    '空气滤清器滤芯': '过滤精度1μm，尺寸φ200×300mm',
    'ISO 68液压油': '18L/桶，粘度等级ISO VG 68',
    '电机散热风扇': '轴流式，φ400mm，380V',
    '冷却器密封垫': '耐油橡胶，适配GA系列',
    '冷却器清洗剂': '5L/桶，弱碱性',
    '油分离器芯': '过滤精度0.1μm',
    '油泵滤网': '不锈钢，目数100目',
    '主轴轴承7014C': '尺寸70×110×20mm，P4精度',
    '丝杠轴承组': '含角接触球轴承3件',
    '导轨润滑脂': '2kg/桶，含极压添加剂',
    '刀具组件': '含刀柄和锁紧螺母',
    '刀库定位销': '材质40Cr，淬火HRC45-50',
    '系统散热风扇': 'DC24V，60×60×25mm',
    '滚筒包胶层': '橡胶板，厚度10mm',
    '托辊轴承6204': '尺寸20×47×14mm，P0精度',
    '电机散热风扇罩': '钢板焊接，表面喷塑',
    '输入轴油封': 'TC型，轴径35mm',
    '输出轴油封': 'TC型，轴径60mm',
    '齿轮油': '18L/桶，ISO VG 220',
    'PLC后备电池': '3.6V锂电池，ER14505',
    '通信电缆': 'PROFIBUS DP线，5m',
    'PLC电源模块': '输入AC220V，输出DC24V/2A',
    '保险丝': '2A，5×20mm',
    'I/O模块': '16点输入/16点输出，DC24V',
}

SUPPLIERS = {
    'SKF-BRG-6205轴承': 'SKF中国',
    'SHC 625润滑脂': '壳牌中国',
    '液压阀密封件组套': '派克汉尼汾',
    '液压油过滤器': '颇尔过滤',
    '止逆环组件': '海天精工',
    '螺杆密封环': '恩格尔机械',
    '模温机加热管': '信易电热',
    '温度传感器PT100': '欧姆龙',
    '格林柱润滑组件': '海天精工',
    '空气滤清器滤芯': '阿特拉斯·科普柯',
    'ISO 68液压油': '壳牌中国',
    '电机散热风扇': '施乐百',
    '冷却器密封垫': '阿特拉斯·科普柯',
    '冷却器清洗剂': '福斯润滑油',
    '油分离器芯': '阿特拉斯·科普柯',
    '油泵滤网': '复盛空压机',
    '主轴轴承7014C': 'FAG中国',
    '丝杠轴承组': 'NSK中国',
    '导轨润滑脂': '克鲁勃润滑剂',
    '刀具组件': '山特维克',
    '刀库定位销': '发那科',
    '系统散热风扇': '三菱电机',
    '滚筒包胶层': '华欧输送带',
    '托辊轴承6204': 'SKF中国',
    '电机散热风扇罩': '皖南电机',
    '输入轴油封': 'NOK',
    '输出轴油封': 'NOK',
    '齿轮油': '壳牌中国',
    'PLC后备电池': '松下电器',
    '通信电缆': '西门子',
    'PLC电源模块': '西门子',
    '保险丝': '正泰电器',
    'I/O模块': '西门子',
}

PART_UNITS = {}
for part_name, spec in PART_SPECS.items():
    if any(kw in part_name for kw in ['润滑脂', '液压油', '齿轮油', '清洗剂']):
        PART_UNITS[part_name] = '桶'
    elif '电缆' in part_name:
        PART_UNITS[part_name] = '根'
    else:
        PART_UNITS[part_name] = '个'

TECHNICIANS = [
    {'username': 'tech_zhang', 'real_name': '张师傅', 'role': 'TECHNICIAN', 'skills': '注塑机,液压系统'},
    {'username': 'tech_li', 'real_name': '李师傅', 'role': 'TECHNICIAN', 'skills': '数控机床,PLC'},
    {'username': 'tech_wang', 'real_name': '王师傅', 'role': 'TECHNICIAN', 'skills': '空压机,输送设备'},
    {'username': 'tech_zhao', 'real_name': '赵师傅', 'role': 'TECHNICIAN', 'skills': '电气系统,自动化'},
    {'username': 'tech_liu', 'real_name': '刘师傅', 'role': 'TECHNICIAN', 'skills': '机械维修,焊接'},
    {'username': 'admin', 'real_name': '管理员', 'role': 'ADMIN', 'skills': ''},
    {'username': 'supervisor_chen', 'real_name': '陈主管', 'role': 'SUPERVISOR', 'skills': ''},
]


def generate_devices(count=500):
    """生成设备数据"""
    devices = []
    type_counts = {t: int(count * w) for t, w in zip(DEVICE_TYPES, TYPE_WEIGHTS)}
    # 补齐余数
    diff = count - sum(type_counts.values())
    type_counts[DEVICE_TYPES[0]] += diff

    for dt, dt_count in type_counts.items():
        for i in range(dt_count):
            mfr = random.choice(MANUFACTURERS[dt])
            model_series = random.choice(MODELS[dt])
            prefix = mfr[0].upper() + model_series[0].upper()
            capacity = random.randint(300, 5000)
            suffix = random.choice(['A', 'B', 'C', 'D', 'E'])
            device_code = f"{prefix}-{capacity}{suffix}"

            workshop = random.choice(['A', 'B', 'C', 'D'])
            line = random.randint(1, 5)
            station = random.randint(1, 20)
            location = f"{workshop}车间-{line:02d}线-{station:02d}号"

            year = random.randint(2020, 2024)
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            pd = date(year, month, day)
            we = date(year + 3 + random.randint(0, 1), month, day)

            devices.append(Device(
                device_code=device_code,
                device_name=f"{mfr}{model_series}-{capacity}{suffix}",
                device_type=dt,
                model=model_series,
                manufacturer=mfr,
                location=location,
                purchase_date=pd,
                warranty_expiry=we,
                remark=random.choice(REMARKS[dt]),
            ))
    return devices


def generate_spare_parts():
    """生成备件数据"""
    seen = set()
    parts = []
    for dt, templates in FAULT_TEMPLATES.items():
        for tpl in templates:
            for part in tpl['used_parts']:
                name = part['name']
                if name in seen:
                    continue
                seen.add(name)
                spec = PART_SPECS.get(name, '标准规格')
                unit = PART_UNITS.get(name, '个')
                stock = random.randint(5, 30)
                safety = max(3, stock // 3)
                price_map = {
                    '轴承': 150, '润滑脂': 200, '密封件': 80, '过滤器': 100,
                    '滤芯': 80, '液压油': 300, '传感器': 120, '电缆': 50,
                    '电源模块': 800, 'I/O模块': 600, '散热风扇': 60,
                }
                price = 50
                for kw, p in price_map.items():
                    if kw in name:
                        price = p + random.randint(-20, 20)
                        break
                part_code = f"SP-{len(parts)+1:04d}"
                parts.append(SparePart(
                    part_code=part_code,
                    part_name=name,
                    specification=spec,
                    unit=unit,
                    stock_quantity=stock,
                    safety_stock=safety,
                    unit_price=price,
                    device_type=dt,
                    location=f"仓库-{random.choice(['A','B','C'])}区-{random.randint(1,10):02d}排",
                    supplier=SUPPLIERS.get(name, '通用供应商'),
                ))
    return parts


def generate_work_orders(devices, technicians):
    """生成维修工单"""
    orders = []
    statuses = list(WorkOrderStatus)
    wo_counter = 1

    # 让每台设备有 1-3 个工单
    for device in devices:
        num_orders = random.choices([1, 2, 3], weights=[0.5, 0.3, 0.2])[0]
        templates = FAULT_TEMPLATES.get(device.device_type, [])
        if not templates:
            continue

        for _ in range(num_orders):
            tpl = random.choice(templates)
            status = random.choices(
                [WorkOrderStatus.COMPLETED, WorkOrderStatus.DRAFT, WorkOrderStatus.IN_PROGRESS],
                weights=[0.7, 0.15, 0.15],
            )[0]

            today = datetime.utcnow()
            days_ago = random.randint(1, 365)
            created = today - timedelta(days=days_ago)
            start = created + timedelta(hours=random.randint(1, 8))
            end = start + timedelta(hours=random.randint(1, 48)) if status == WorkOrderStatus.COMPLETED else None

            technician = random.choice(technicians) if technicians else None
            priority = tpl.get('priority', 'MEDIUM')

            wo_no = f"WO-{created.strftime('%Y%m%d')}-{wo_counter:03d}"
            wo_counter += 1

            orders.append(WorkOrder(
                work_order_no=wo_no,
                device_id=device.id,
                device_code=device.device_code,
                fault_code=tpl['fault_code'],
                fault_description=tpl['fault_description'],
                fault_phenomenon=tpl['fault_phenomenon'],
                root_cause=tpl['root_cause'],
                solution_steps=tpl['solution_steps'],
                used_parts=tpl['used_parts'],
                start_time=start,
                end_time=end,
                technician_id=technician.id if technician else None,
                assignee_id=technician.id if technician else None,
                priority=priority,
                location=device.location,
                status=status,
                tags=tpl['tags'],
                created_at=created,
                updated_at=end or created,
            ))
    return orders


def generate_knowledge(work_orders):
    """从已完成的工单提取知识条目"""
    from app.models.knowledge import KnowledgeStatus
    knowledge = []
    seen_faults = set()

    for wo in work_orders:
        if wo.status != WorkOrderStatus.COMPLETED:
            continue
        key = (wo.fault_code, wo.device_code)
        if key in seen_faults:
            continue
        seen_faults.add(key)

        tags = wo.tags or []
        knowledge.append(KnowledgeItem(
            title=f"【{wo.device.device_type}】{wo.fault_description}的处理方法",
            content=(
                f"故障现象：{wo.fault_phenomenon}\n"
                f"原因分析：{wo.root_cause}\n"
                f"处理步骤：{wo.solution_steps}"
            ),
            device_type=wo.device.device_type,
            fault_code=wo.fault_code,
            fault_tags=tags,
            source_type='WORK_ORDER',
            source_id=wo.id,
            status=KnowledgeStatus.PUBLISHED,
            version=1,
        ))
    return knowledge


def clean_data(db):
    """清空所有数据（按外键约束逆序）"""
    print("正在清空已有数据...")
    db.execute(text("DELETE FROM work_orders"))
    db.execute(text("DELETE FROM knowledge_items"))
    db.execute(text("DELETE FROM spare_parts"))
    db.execute(text("DELETE FROM devices"))
    db.execute(text("DELETE FROM users"))
    db.commit()
    print("  已清空所有数据")


def run():
    db = SessionLocal()
    try:
        # 1. 清空数据
        clean_data(db)

        # 2. 创建用户
        print("创建用户...")
        users = []
        for u in TECHNICIANS:
            user = User(
                username=u['username'],
                password_hash='240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9',  # admin123
                real_name=u['real_name'],
                role=u['role'],
                is_active=True,
                skills=u['skills'],
            )
            db.add(user)
            db.flush()
            users.append(user)
        db.commit()
        print(f"  创建了 {len(users)} 个用户")

        # 3. 生成设备
        print("生成设备数据...")
        devices = generate_devices(500)
        for d in devices:
            db.add(d)
        db.flush()
        print(f"  生成了 {len(devices)} 台设备")

        # 4. 生成备件
        print("生成备件数据...")
        parts = generate_spare_parts()
        for p in parts:
            db.add(p)
        db.flush()
        print(f"  生成了 {len(parts)} 种备件")

        # 5. 生成工单
        print("生成工单数据...")
        orders = generate_work_orders(devices, users)
        for o in orders:
            db.add(o)
        db.flush()
        print(f"  生成了 {len(orders)} 个工单")

        # 6. 生成知识条目
        print("生成知识条目...")
        knowledge = generate_knowledge(orders)
        for k in knowledge:
            db.add(k)
        db.flush()
        print(f"  生成了 {len(knowledge)} 条知识")

        db.commit()
        print(f"\n{'='*50}")
        print(f"✅ 种子数据生成完成！")
        print(f"   用户: {len(users)}")
        print(f"   设备: {len(devices)}")
        print(f"   备件: {len(parts)}")
        print(f"   工单: {len(orders)}")
        print(f"   知识: {len(knowledge)}")
        print(f"{'='*50}")

    except Exception as e:
        db.rollback()
        print(f"\n❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
