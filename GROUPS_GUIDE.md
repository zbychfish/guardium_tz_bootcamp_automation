# Groups System - Quick Guide

## Concept
**Group** = zestaw stage'ów wykonywanych razem jako logiczna całość (np. lab szkoleniowy)

## Structure
```
Group (initial_preparation)
  ├─ Stage: setup_hosts
  ├─ Stage: preparation_for_services_deployment
  ├─ Stage: deploy_mysql_on_raptor
  ├─ Stage: deploy_mongo_on_raptor
  └─ Stage: deploy_oracle_on_sauropod
```

## Configuration: `config/groups.yaml`
```yaml
groups:
  group_name:
    name: "Display Name"
    description: "What this group does"
    auto_execute: true/false  # true = before marker, false = manual
    stages:
      - name: stage_id
        function: function_name
        module: tasks.module_name
        description: "What this stage does"
```

## Usage

### List available groups
```bash
python automation.py --list-groups
```

### Run auto-execute groups (default)
```bash
python automation.py
```

### Run specific group
```bash
python automation.py --group atap_lab
```

### Run multiple groups
```bash
python automation.py --group initial_preparation --group atap_lab
```

### Check status
```bash
python automation.py --status
```

**Example output:**
```
================================================================================
AUTOMATION STATUS
================================================================================

[AUTO] initial_preparation: Initial Preparation
  Basic system setup and database deployments before marker creation
    ✓ setup_hosts
    ✓ preparation_for_services_deployment
    ✓ deploy_mysql_on_raptor
    ○ deploy_mongo_on_raptor
    ○ deploy_oracle_on_sauropod
  Progress: 3/5 stages completed

[MANUAL] atap_lab: ATAP Lab
  PostgreSQL deployment for ATAP training
    ○ deploy_postgres_on_raptor
  Progress: 0/1 stages completed

================================================================================
Total completed stages: 3
================================================================================
```

Legend:
- `✓` = completed stage
- `○` = pending stage
- `[AUTO]` = auto-execute group (runs before marker)
- `[MANUAL]` = manual group (runs on demand)

### Reset state
```bash
python automation.py --reset
```

### Remove specific stage
```bash
python automation.py --remove-stage initial_preparation.setup_hosts
```

## State Format
State uses `group_name.stage_name` format:
- `initial_preparation.setup_hosts`
- `initial_preparation.deploy_mysql_on_raptor`
- `atap_lab.deploy_postgres_on_raptor`

## Adding New Group

1. **Add to `config/groups.yaml`:**
```yaml
  my_new_lab:
    name: "My New Lab"
    description: "Description of the lab"
    auto_execute: false
    stages:
      - name: my_stage
        function: my_function
        module: tasks.my_module
        description: "What it does"
```

2. **Create stage function in `tasks/my_module.py`:**
```python
def my_function(config, logger, verbose: bool = True) -> bool:
    """Stage implementation"""
    # Your code here
    return True
```

3. **Run:**
```bash
python automation.py --group my_new_lab
```

## Current Groups

### initial_preparation (auto_execute: true)
- setup_hosts
- preparation_for_services_deployment
- deploy_mysql_on_raptor
- deploy_mongo_on_raptor
- deploy_oracle_on_sauropod

### atap_lab (auto_execute: false)
- deploy_postgres_on_raptor

---
Made with Bob