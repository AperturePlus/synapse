# Synapse

Code topology modeling system based on Neo4j.

## Installation

```bash
uv sync
```

## Usage

```bash
# Project management
synapse init <project-path>          # Register a project
synapse scan <project-id>            # Scan project code
synapse list-projects                # List active projects
synapse list-projects --include-archived  # Include archived projects

# Project lifecycle
synapse delete <project-id>          # Archive a project (soft delete)
synapse restore <project-id>         # Restore an archived project
synapse purge <project-id>           # Permanently delete an archived project

# Queries
synapse query calls <callable-id>    # Query call chains
synapse query types <type-id>        # Query type hierarchy
synapse query modules <module-id>    # Query module dependencies
```

## Configuration

Synapse uses environment variables with the `SYNAPSE_` prefix. For backward compatibility, Neo4j variables also support unprefixed names (e.g., `NEO4J_URI`), with `SYNAPSE_` prefix taking precedence.

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNAPSE_NEO4J_URI` | `neo4j://localhost:7687` | Neo4j connection URI |
| `SYNAPSE_NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `SYNAPSE_NEO4J_PASSWORD` | (empty) | Neo4j password |
| `SYNAPSE_NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `SYNAPSE_DEFAULT_PAGE_SIZE` | `100` | Default pagination size |
| `SYNAPSE_DEFAULT_MAX_DEPTH` | `5` | Max depth for graph traversals |
| `SYNAPSE_BATCH_WRITE_SIZE` | `1000` | Batch size for bulk write operations |

You can also use a `.env` file in the project root.
