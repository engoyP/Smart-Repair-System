-- 混合库方案：向量存储由 Milvus 管理，PostgreSQL 仅存储关系型数据

-- 创建枚举类型
CREATE TYPE work_order_status AS ENUM (
    'SUBMITTED',
    'STANDARDIZED',
    'CLASSIFIED',
    'APPROVED',
    'REJECTED',
    'ARCHIVED'
);

CREATE TYPE knowledge_status AS ENUM (
    'DRAFT',
    'UNDER_REVIEW',
    'PUBLISHED',
    'DEPRECATED',
    'ARCHIVED'
);

-- 设备表
CREATE TABLE IF NOT EXISTS devices (
    id SERIAL PRIMARY KEY,
    device_code VARCHAR(50) UNIQUE NOT NULL,
    device_name VARCHAR(200) NOT NULL,
    device_type VARCHAR(100),
    model VARCHAR(100),
    manufacturer VARCHAR(200),
    location VARCHAR(200),
    purchase_date DATE,
    warranty_expiry DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 工单表
CREATE TABLE IF NOT EXISTS work_orders (
    id SERIAL PRIMARY KEY,
    work_order_no VARCHAR(50) UNIQUE NOT NULL,
    device_id INTEGER REFERENCES devices(id),
    fault_code TEXT,

    fault_description TEXT NOT NULL,
    fault_phenomenon TEXT,
    root_cause TEXT,
    solution_steps TEXT,
    used_parts JSONB,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    technician_id INTEGER,
    status work_order_status DEFAULT 'SUBMITTED',
    tags JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 知识条目表（仅存储元数据，向量存储由 Milvus 管理）
CREATE TABLE IF NOT EXISTS knowledge_items (
    id SERIAL PRIMARY KEY,
    milvus_id VARCHAR(100) UNIQUE,  -- Milvus 中的向量 ID
    title VARCHAR(300) NOT NULL,
    content TEXT NOT NULL,
    device_type VARCHAR(100),
    fault_code TEXT,

    fault_tags JSONB,
    source_type VARCHAR(20),  -- 'WORK_ORDER' 或 'DOCUMENT'
    source_id INTEGER,
    status knowledge_status DEFAULT 'DRAFT',
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 备件表
CREATE TABLE IF NOT EXISTS spare_parts (
    id SERIAL PRIMARY KEY,
    part_code VARCHAR(50) UNIQUE NOT NULL,
    part_name VARCHAR(200) NOT NULL,
    specification VARCHAR(200),
    applicable_devices JSONB,
    safety_stock INTEGER DEFAULT 0,
    current_stock INTEGER DEFAULT 0,
    in_transit_stock INTEGER DEFAULT 0,
    unit VARCHAR(20),
    unit_price DECIMAL(10, 2),
    supplier VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 故障码映射表（故障码与故障名称一一对应，系统生成，只读）
CREATE TABLE IF NOT EXISTS fault_code_mappings (
    id SERIAL PRIMARY KEY,
    fault_code VARCHAR(100) UNIQUE NOT NULL,
    fault_description TEXT NOT NULL,
    device_type VARCHAR(100),
    source VARCHAR(20) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS fault_code_mappings_code_idx ON fault_code_mappings(fault_code);
CREATE INDEX IF NOT EXISTS fault_code_mappings_device_idx ON fault_code_mappings(device_type);

-- 全文搜索索引（使用默认 simple 分词器，中文支持需安装 zhparser 扩展）
-- 如需中文全文搜索，需执行: CREATE EXTENSION zhparser; 然后使用 to_tsvector('chinese', ...)
CREATE INDEX IF NOT EXISTS knowledge_content_fts_idx ON knowledge_items 
USING gin (to_tsvector('simple', content));

CREATE INDEX IF NOT EXISTS work_order_fts_idx ON work_orders 
USING gin (to_tsvector('simple', fault_description || ' ' || COALESCE(solution_steps, '')));

-- 创建时间索引
CREATE INDEX IF NOT EXISTS work_orders_created_at_idx ON work_orders(created_at);
CREATE INDEX IF NOT EXISTS knowledge_items_created_at_idx ON knowledge_items(created_at);

-- 注释
COMMENT ON TABLE devices IS '设备信息表';
COMMENT ON TABLE work_orders IS '维修工单表';
COMMENT ON TABLE knowledge_items IS '知识条目表（含向量字段）';
COMMENT ON TABLE spare_parts IS '备件库存表';