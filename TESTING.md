# Synapse 测试指南

本文档提供 Synapse MVP 的完整测试流程。

## 前置条件

### 1. 安装依赖

```bash
uv sync
```

### 2. 启动 Neo4j 数据库

确保 Neo4j 数据库正在运行。可以使用 Docker：

```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:latest
```

### 3. 配置环境变量

复制 `.env.example` 到 `.env` 并配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
SYNAPSE_NEO4J_URI=bolt://localhost:7687
SYNAPSE_NEO4J_USERNAME=neo4j
SYNAPSE_NEO4J_PASSWORD=your_password
SYNAPSE_NEO4J_DATABASE=neo4j
```

## 测试层级

### 1. 单元测试（Unit Tests）

测试独立模块和函数，不依赖外部服务。

```bash
# 运行所有单元测试
uv run pytest tests/unit/ -v

# 运行特定测试文件
uv run pytest tests/unit/test_models.py -v
uv run pytest tests/unit/test_config.py -v
uv run pytest tests/unit/test_writer.py -v

# 查看覆盖率
uv run pytest tests/unit/ --cov=synapse --cov-report=html
```

**测试内容：**
- 数据模型验证（`test_models.py`）
- 配置管理（`test_config.py`）
- 图写入器（`test_writer.py`）

### 2. 集成测试（Integration Tests）

测试语言适配器与真实代码的集成。

```bash
# 运行所有集成测试
uv run pytest tests/integration/ -v

# 测试 Java 适配器
uv run pytest tests/integration/test_java_adapter.py -v

# 测试 Go 适配器
uv run pytest tests/integration/test_go_adapter.py -v
```

**测试内容：**
- Java 代码解析和 IR 生成
- Go 代码解析和 IR 生成
- 符号表构建
- 引用解析
- ID 确定性

### 3. 属性测试（Property Tests）

使用 Hypothesis 进行基于属性的测试。

```bash
# 运行所有属性测试
uv run pytest tests/property/ -v

# 测试特定属性
uv run pytest tests/property/test_idempotency.py -v
uv run pytest tests/property/test_roundtrip.py -v
```

**测试内容：**
- 适配器确定性（相同输入产生相同输出）
- 图写入幂等性（多次写入结果一致）
- IR 序列化往返一致性
- 分页一致性
- 验证器正确性

### 4. 端到端测试（E2E Tests）

测试完整的 CLI 工作流，需要 Neo4j 连接。

```bash
# 运行所有 E2E 测试
uv run pytest tests/e2e/ -v

# 测试特定命令
uv run pytest tests/e2e/test_cli.py::TestInitCommand -v
uv run pytest tests/e2e/test_cli.py::TestScanCommand -v
```

**测试内容：**
- CLI 命令帮助信息
- 项目注册（`init`）
- 代码扫描（`scan`）
- 查询操作（`query calls/types/modules`）
- 导出功能（`export`）
- 项目管理（`list-projects`, `delete`）

## 完整测试流程

### 运行所有测试

```bash
# 运行所有测试（需要 Neo4j）
uv run pytest -v

# 运行测试并生成覆盖率报告
uv run pytest --cov=synapse --cov-report=term-missing --cov-report=html

# 查看 HTML 覆盖率报告
# 打开 htmlcov/index.html
```

### 快速测试（不需要 Neo4j）

```bash
# 只运行单元测试和集成测试
uv run pytest tests/unit/ tests/integration/ -v
```

## 手动功能测试

### 1. 项目注册

```bash
# 注册一个 Java 项目
uv run synapse init /path/to/java/project --name "My Java Project"

# 注册一个 Go 项目
uv run synapse init /path/to/go/project --name "My Go Project"

# 列出所有项目
uv run synapse list-projects
```

### 2. 代码扫描

```bash
# 扫描项目（使用返回的项目 ID）
uv run synapse scan <project-id>

# 使用 verbose 模式查看详细信息
uv run synapse -v scan <project-id>
```

### 3. 查询拓扑

```bash
# 查询调用链
uv run synapse query calls <callable-id> --direction callees --depth 3

# 查询类型层次
uv run synapse query types <type-id> --direction ancestors

# 查询模块依赖
uv run synapse query modules <module-id>
```

### 4. 导出数据

```bash
# 导出项目 IR 到 JSON
uv run synapse export <project-id> -o output.json
```

### 5. 删除项目

```bash
# 删除项目（需要确认）
uv run synapse delete <project-id>

# 强制删除（跳过确认）
uv run synapse delete <project-id> --force
```

## 测试示例项目

项目包含测试 fixtures，位于 `tests/fixtures/`：

### Java 示例

```bash
# 扫描 Java 测试项目
uv run synapse init tests/fixtures/java-sample --name "Java Sample"
uv run synapse scan <project-id>
```

### Go 示例

```bash
# 扫描 Go 测试项目
uv run synapse init tests/fixtures/go-sample --name "Go Sample"
uv run synapse scan <project-id>
```

## 代码质量检查

### 类型检查

```bash
uv run mypy src/
```

### 代码格式化

```bash
# 检查格式
uv run ruff check src/ tests/

# 自动修复
uv run ruff check --fix src/ tests/

# 格式化代码
uv run ruff format src/ tests/
```

## 性能测试

### 批量写入性能

可以通过环境变量调整批量大小：

```bash
# 使用较小的批量大小
SYNAPSE_BATCH_WRITE_SIZE=500 uv run synapse scan <project-id>

# 使用较大的批量大小
SYNAPSE_BATCH_WRITE_SIZE=2000 uv run synapse scan <project-id>
```

## 故障排查

### 测试失败

1. **Neo4j 连接失败**
   - 确认 Neo4j 正在运行
   - 检查 `.env` 中的连接配置
   - 验证用户名和密码

2. **导入错误**
   - 运行 `uv sync` 重新安装依赖
   - 检查 Python 版本（需要 3.11+）

3. **测试数据库污染**
   - E2E 测试使用独立的测试数据库
   - 可以手动清理：`MATCH (n) DETACH DELETE n`

### 查看详细日志

```bash
# 使用 verbose 模式
uv run synapse -v <command>

# 查看 pytest 详细输出
uv run pytest -vv --tb=long
```

## CI/CD 集成

项目测试可以集成到 CI/CD 流程：

```yaml
# GitHub Actions 示例
- name: Run tests
  run: |
    uv sync
    uv run pytest --cov=synapse --cov-report=xml
    
- name: Upload coverage
  uses: codecov/codecov-action@v3
```

## 测试覆盖率目标

- **单元测试**: > 80%
- **集成测试**: 核心适配器功能
- **E2E 测试**: 所有 CLI 命令
- **属性测试**: 关键不变量

## 下一步

完成测试后，可以：

1. 查看覆盖率报告识别未测试代码
2. 添加更多边界情况测试
3. 性能基准测试
4. 压力测试（大型项目）
5. 安全测试（注入攻击等）
