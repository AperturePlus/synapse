# Synapse

Code topology modeling system based on Neo4j.

## Installation

```bash
uv sync
```

## Usage

```bash
synapse init <project-path>
synapse scan <project-id>
synapse query calls <callable-id>
```

## Configuration

Synapse uses environment variables with the `SYNAPSE_` prefix. For backward compatibility, Neo4j variables also support unprefixed names (e.g., `NEO4J_URI`), with `SYNAPSE_` prefix taking precedence.

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNAPSE_NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `SYNAPSE_NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `SYNAPSE_NEO4J_PASSWORD` | (empty) | Neo4j password |
| `SYNAPSE_NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `SYNAPSE_DEFAULT_PAGE_SIZE` | `100` | Default pagination size |
| `SYNAPSE_DEFAULT_MAX_DEPTH` | `5` | Max depth for graph traversals |
| `SYNAPSE_BATCH_WRITE_SIZE` | `1000` | Batch size for bulk write operations |

You can also use a `.env` file in the project root.
