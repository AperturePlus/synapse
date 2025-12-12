# Synapse 快速开始

5 分钟快速体验 Synapse 代码拓扑建模系统。

## 1. 环境准备（2 分钟）

### 安装依赖

```bash
# 克隆项目
git clone <your-repo-url>
cd synapse

# 安装依赖
uv sync
```

### 启动 Neo4j

使用 Docker 快速启动：

```bash
docker run -d \
  --name synapse-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/synapse123 \
  neo4j:latest
```

访问 http://localhost:7474 验证 Neo4j 已启动。

### 配置环境

```bash
# 复制配置文件
cp .env.example .env

# 编辑 .env（如果使用上面的 Docker 命令，密码改为 synapse123）
# SYNAPSE_NEO4J_PASSWORD=synapse123
```

## 2. 快速测试（1 分钟）

```bash
# 运行单元测试（不需要 Neo4j）
uv run pytest tests/unit/ -v

# 运行集成测试（测试代码解析）
uv run pytest tests/integration/ -v
```

## 3. 使用 CLI（2 分钟）

### 注册项目

```bash
# 使用测试 fixture 中的 Java 示例
uv run synapse init tests/fixtures/java-sample --name "Java Sample"

# 记录返回的项目 ID，例如：abc123def456
```

### 扫描代码

```bash
# 使用上一步的项目 ID
uv run synapse scan abc123def456
```

你会看到类似输出：

```
✓ Scan completed successfully
  Languages: java
  Modules: 3
  Types: 5
  Callables: 12
```

### 查询拓扑

```bash
# 列出所有项目
uv run synapse list-projects

# 查看帮助
uv run synapse --help
uv run synapse query --help
```

## 4. 在 Neo4j 中查看

打开 Neo4j Browser (http://localhost:7474)，运行查询：

```cypher
// 查看所有节点
MATCH (n) RETURN n LIMIT 25

// 查看模块层次
MATCH (m:Module)-[:CONTAINS]->(sub:Module)
RETURN m, sub

// 查看类型关系
MATCH (t:Type)-[:EXTENDS|IMPLEMENTS]->(parent:Type)
RETURN t, parent

// 查看调用链
MATCH (c:Callable)-[:CALLS]->(target:Callable)
RETURN c, target LIMIT 50
```

## 5. 使用自己的项目

### Java 项目

```bash
# 注册你的 Java 项目
uv run synapse init /path/to/your/java/project --name "My Project"

# 扫描
uv run synapse scan <project-id>

# 查询某个方法的调用链（需要先找到 callable ID）
uv run synapse query calls <callable-id> --direction callees
```

### Go 项目

```bash
# 注册你的 Go 项目
uv run synapse init /path/to/your/go/project --name "My Go Project"

# 扫描
uv run synapse scan <project-id>
```

## 常用命令速查

```bash
# 项目管理
uv run synapse init <path> --name "Project Name"
uv run synapse list-projects
uv run synapse delete <project-id> --force

# 代码扫描
uv run synapse scan <project-id>
uv run synapse -v scan <project-id>  # verbose 模式

# 查询
uv run synapse query calls <callable-id> --direction both --depth 5
uv run synapse query types <type-id> --direction ancestors
uv run synapse query modules <module-id>

# 导出
uv run synapse export <project-id> -o output.json
```

## 配置选项

通过环境变量自定义配置：

```bash
# ID 长度（8-64）
SYNAPSE_ID_LENGTH=20

# 分页大小（1-1000）
SYNAPSE_DEFAULT_PAGE_SIZE=50

# 图遍历深度（1-20）
SYNAPSE_DEFAULT_MAX_DEPTH=10

# 批量写入大小（100-10000）
SYNAPSE_BATCH_WRITE_SIZE=2000
```

## 下一步

- 阅读 [TESTING.md](TESTING.md) 了解完整测试流程
- 阅读 [README.md](README.md) 了解架构设计
- 查看 `.kiro/steering/` 中的项目规范
- 探索 `src/synapse/` 源代码

## 故障排查

### Neo4j 连接失败

```bash
# 检查 Neo4j 是否运行
docker ps | grep neo4j

# 查看 Neo4j 日志
docker logs synapse-neo4j

# 重启 Neo4j
docker restart synapse-neo4j
```

### 测试失败

```bash
# 重新安装依赖
uv sync

# 清理缓存
rm -rf .pytest_cache __pycache__

# 运行单个测试
uv run pytest tests/unit/test_models.py -v
```

### 扫描失败

```bash
# 使用 verbose 模式查看详细错误
uv run synapse -v scan <project-id>

# 检查项目路径是否正确
uv run synapse list-projects
```

## 清理

```bash
# 停止并删除 Neo4j 容器
docker stop synapse-neo4j
docker rm synapse-neo4j

# 清理 Python 环境
rm -rf .venv
```

## 获取帮助

- 查看命令帮助：`uv run synapse <command> --help`
- 查看测试指南：[TESTING.md](TESTING.md)
- 查看项目结构：`.kiro/steering/structure.md`
