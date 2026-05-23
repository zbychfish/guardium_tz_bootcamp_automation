# Coding Guidelines for Guardium TZ Bootcamp Automation

## General Principles

### 0. Documentation Rules

#### ❌ DON'T TOUCH:
- **README.md** - Leave it alone unless explicitly asked
- **Existing documentation** - Don't update without request

#### ✅ DO:
- **Update CODING_GUIDELINES.md** when adding new patterns

### 1. Code Organization and Refactoring

**ALWAYS follow these rules:**

#### ✅ DO:
- **Place reusable functions in `core/` modules** (utils.py, logger.py, etc.)
- **Keep task-specific logic in `tasks/` directory**
- **Export new core functions in `core/__init__.py`**
- **Import from core in tasks**: `from core import function_name`
- **Minimize code duplication** - if a function can be used by multiple tasks, move it to core

#### ❌ DON'T:
- **Don't create general-purpose functions inside task files**
- **Don't duplicate code between tasks**
- **Don't keep utility functions in tasks/** - they belong in core/

### 2. File Structure

```
guardium_tz_bootcamp_automation/
├── core/                      # Reusable components
│   ├── utils.py              # General utility functions
│   ├── logger.py             # Logging setup
│   ├── ssh_client.py         # SSH operations
│   ├── config_loader.py      # Configuration management
│   ├── state_manager.py      # State tracking
│   └── __init__.py           # Exports
│
├── tasks/                     # Task-specific implementations
│   ├── setup_hosts.py        # Host configuration tasks
│   ├── deploy_mysql.py       # MySQL deployment tasks
│   └── ...                   # Other specific tasks
│
├── config/                    # Configuration files
│   └── config.yaml
│
└── automation.py              # Main orchestration script
```

### 3. Function Placement Rules

| Function Type | Location | Example |
|---------------|----------|---------|
| Command execution | `core/utils.py` | `execute_local_command()`, `execute_mysql_sql()` |
| File operations | `core/utils.py` | `read_file()`, `write_file()` |
| SSH operations | `core/ssh_client.py` | `SSHClient.execute_command()` |
| Configuration | `core/config_loader.py` | `get_machine()`, `get_custom_variable()` |
| State management | `core/state_manager.py` | `mark_completed()`, `is_completed()` |
| Task-specific logic | `tasks/*.py` | `setup_hosts_locally()`, `deploy_mysql_on_raptor()` |

### 4. Import Pattern

**In task files:**
```python
#!/usr/bin/env python3
import sys
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

# Import from core
from core import execute_local_command, execute_mysql_sql, get_logger

# Task-specific code here
def my_task(logger):
    result = execute_local_command("ls -la", logger)
    # ...
```

### 5. When to Create New Core Functions

Create a new function in `core/utils.py` when:
- ✅ Function can be used by multiple tasks
- ✅ Function is a general-purpose utility (command execution, file ops, etc.)
- ✅ Function doesn't contain task-specific business logic
- ✅ Function would reduce code duplication

Keep function in `tasks/` when:
- ✅ Function is specific to one task's business logic
- ✅ Function orchestrates multiple core functions for a specific purpose
- ✅ Function contains domain-specific logic (e.g., MySQL password setup flow)
### 6. Verbose Mode

**ALWAYS pass `verbose` parameter through the call chain:**

```python
# In automation.py - pass args.verbose to tasks
orchestrator.register_task(
    task_id="my_task",
    task_fn=lambda: my_task_function(logger, verbose=args.verbose),
    description="Task description"
)

# In tasks/*.py - accept verbose and pass to core functions
def my_task_function(logger, verbose: bool = True):
    result = execute_local_command("command", logger, verbose)
    result = execute_mysql_sql("SQL", logger=logger, verbose=verbose)
    return True

# In core/utils.py - use verbose to control logging
def execute_local_command(command: str, logger=None, verbose: bool = True):
    if verbose:
        logger.info(f"Executing: {command}")
    # ... execution ...
    if verbose and result['stdout']:
        logger.info(f"Output: {result['stdout']}")
```

**Rules:**
- ✅ All task functions MUST accept `verbose` parameter (default: True)
- ✅ All core utility functions MUST accept `verbose` parameter (default: True)
- ✅ Always pass `verbose` from automation.py → tasks → core functions
- ✅ Use `verbose` to control detailed logging (commands, outputs)
- ✅ Always log errors regardless of verbose mode


### 7. Logging

**Default behavior (concise):**
```python
➤  task_name
✓  task_name
```

**Verbose mode (`--verbose` or `-v`):**
```python
➤  Running: task_name
   Description: Full task description
✓  Completed: task_name
```

**In code:**
```python
if self.verbose:
    self.logger.info(f"➤  Running: {task_id}")
    if description:
        self.logger.info(f"   Description: {description}")
else:
    self.logger.info(f"➤  {task_id}")
```

### 8. Error Handling

```python
try:
    result = some_operation()
    if result['rc'] != 0:
        logger.error(f"Operation failed")
        return False
    return True
except Exception as e:
    logger.error(f"Exception: {e}", exc_info=verbose_mode)
    return False
```

### 9. SQL Operations

**Always use `execute_mysql_sql()` from core:**
```python
from core import execute_mysql_sql

result = execute_mysql_sql(
    sql_commands="CREATE DATABASE mydb;",
    username="root",
    password="password",
    logger=logger
)
```

**Don't create custom SQL execution in tasks.**

### 10. Command Execution

**Use appropriate function from core:**

```python
from core import execute_local_command, execute_mysql_sql

# For shell commands
result = execute_local_command("dnf install -y package", logger)

# For MySQL SQL
result = execute_mysql_sql("CREATE DATABASE db;", username="root", password="pass", logger=logger)
```

### 11. State Management

```python
# Check if task completed
if orchestrator.state.is_completed(task_id):
    return True

# Mark task as completed
orchestrator.state.mark_completed(task_id)

# Remove task from state (for re-execution)
orchestrator.state.remove_task(task_id)

# Reset all state
orchestrator.state.reset()
```

## Examples

### ✅ GOOD: Reusable function in core

```python
# core/utils.py
def execute_mysql_sql(sql_commands, username="root", password="", logger=None):
    """General-purpose MySQL execution"""
    # Implementation
    pass
```

```python
# tasks/deploy_mysql.py
from core import execute_mysql_sql

def setup_mysql_database(db_name, logger):
    """Task-specific: Setup specific database"""
    sql = f"CREATE DATABASE {db_name};"
    return execute_mysql_sql(sql, username="root", password="pass", logger=logger)
```

### ❌ BAD: General function in task file

```python
# tasks/deploy_mysql.py
def execute_mysql_sql(sql_commands, username="root", password=""):
    """This should be in core/utils.py!"""
    # Implementation
    pass

def setup_mysql_database(db_name, logger):
    sql = f"CREATE DATABASE {db_name};"
    return execute_mysql_sql(sql, username="root", password="pass")
```

## Refactoring Checklist

When adding new functionality:

1. ☐ Is this function reusable? → Move to `core/utils.py`
2. ☐ Does it duplicate existing code? → Use existing core function
3. ☐ Is it task-specific business logic? → Keep in `tasks/`
4. ☐ Did I add export to `core/__init__.py`? → Yes
5. ☐ Did I import from core in task? → Yes
6. ☐ Did I test the refactored code? → Yes

## Communication Guidelines

### Task Completion Messages

**Keep completion messages SHORT and FOCUSED:**

#### ✅ GOOD (Concise):
```
Added execute_mysql_sql() to core/utils.py
- Moved from tasks/deploy_mysql.py
- Exported in core/__init__.py
- Updated deploy_mysql.py to import from core
```

#### ❌ BAD (Too verbose):
```
I have successfully completed the refactoring of the MySQL execution
functionality. This involved moving the execute_mysql_sql() function
from the tasks/deploy_mysql.py file to the core/utils.py file where
it belongs according to our coding guidelines. I then updated the
core/__init__.py file to export this new function so that it can be
imported by other modules. Finally, I modified the tasks/deploy_mysql.py
file to import this function from core instead of defining it locally.
This refactoring improves code reusability and maintainability...
[continues for 10 more lines]
```

**Format:**
- Start with what was done (1 line)
- Bullet points for key changes (3-5 max)
- No repetition of the task description
- No unnecessary explanations

## Summary

**Golden Rule:** If a function can be used by more than one task or is a general utility, it belongs in `core/`, not in `tasks/`.

This keeps the codebase:
- ✅ DRY (Don't Repeat Yourself)
- ✅ Maintainable
- ✅ Testable
- ✅ Scalable

# Made with Bob