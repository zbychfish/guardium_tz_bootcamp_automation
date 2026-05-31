# Coding Guidelines for Guardium TZ Bootcamp Automation

## General Principles

### 0. Documentation Rules

#### ❌ DON'T TOUCH:
- **README.md** - Leave it alone unless explicitly asked
- **Existing documentation** - Don't update without request

#### ✅ DO:
- **Update CODING_GUIDELINES.md** when adding new patterns

### 0.1. Commented Code Rules

#### ❌ DON'T DELETE:
- **Commented-out code** (e.g., `# command_to_run()`) - This is temporarily disabled code that may be needed
- **Alternative implementations** - Code that shows different approaches

#### ✅ CAN DELETE:
- **Explanatory comments** that are outdated or redundant
- **TODO comments** that have been completed

**Example of what NOT to delete:**
```python
commands = [
    # "dnf install -y mongodb-enterprise-database",  # DON'T DELETE - alternative option
    # "dnf install -y mongodb-enterprise-tools",     # DON'T DELETE - alternative option
    "dnf install -y mongodb-enterprise",             # Current active command
]
```

**Why:** Commented code often represents:
- Alternative installation methods
- Temporarily disabled features
- Different configuration options
- Debugging alternatives

**Rule:** When refactoring, preserve commented code unless explicitly asked to remove it.

### 1. Code Organization and Refactoring

**ALWAYS follow these rules:**

#### ✅ DO:
- **Place reusable functions in `core/` modules** (utils.py, logger.py, etc.)
- **Keep task-specific logic in `tasks/` directory**
- **Export new core functions in `core/__init__.py`**
- **Import from core in tasks**: `from core import function_name`
- **Minimize code duplication** - if a function can be used by multiple tasks, move it to core
- **Create specialized core modules** for domain-specific operations (e.g., `appliance_operations.py`)

#### ❌ DON'T:
- **Don't create general-purpose functions inside task files**
- **Don't duplicate code between tasks**
- **Don't keep utility functions in tasks/** - they belong in core/

### 1.1. Keeping Code DRY (Don't Repeat Yourself)

**CRITICAL RULE: Extract reusable code to core modules**

When you notice:
- ✅ **Same logic in multiple tasks** → Extract to `core/`
- ✅ **Complex operation repeated** → Create dedicated core function
- ✅ **Domain-specific operations** → Create specialized core module

#### Example: Appliance Operations

**❌ BAD - Duplicated code in tasks:**
```python
# tasks/setup_appliances.py
def restart_appliance(...):
    # 150 lines of restart logic
    pass

# tasks/maintenance_tasks.py
def restart_appliance(...):
    # Same 150 lines duplicated!
    pass
```

**✅ GOOD - Reusable core function:**
```python
# core/appliance_operations.py
def restart_appliance(config, logger, appliance_name, ...):
    """Reusable restart function for any appliance"""
    # 150 lines of restart logic - ONE place
    pass

# tasks/setup_appliances.py
from core.appliance_operations import restart_appliance

def my_task(config, logger, **kwargs):
    return restart_appliance(config, logger, "cm01")

# tasks/maintenance_tasks.py
from core.appliance_operations import restart_appliance

def my_other_task(config, logger, **kwargs):
    return restart_appliance(config, logger, "cm02")
```

#### Core Module Organization

Create specialized modules in `core/` for different domains:

```
core/
├── utils.py                    # General utilities (file ops, command execution)
├── logger.py                   # Logging setup
├── ssh_client.py              # SSH operations
├── config_loader.py           # Configuration management
├── state_manager.py           # State tracking
├── appliance_operations.py    # Appliance-specific operations (restart, configure, etc.)
├── guardium_rest_api.py       # Guardium REST API operations
└── appliance_client.py        # Appliance CLI client
```

#### When to Create New Core Module

Create a new specialized module when:
- ✅ You have 3+ related functions for a specific domain
- ✅ Functions are reusable across multiple tasks
- ✅ Logic is complex enough to warrant separation
- ✅ Domain has its own data structures/patterns

**Example domains:**
- `appliance_operations.py` - Appliance management (restart, configure, backup)
- `database_operations.py` - Database operations (backup, restore, migrate)
- `network_operations.py` - Network configuration (firewall, routing)

#### Task Files as Thin Wrappers

Task functions should be **thin wrappers** that:
- ✅ Call core functions with appropriate parameters
- ✅ Handle task-specific orchestration
- ✅ Provide backward compatibility for stage definitions
- ✅ Add minimal task-specific logic

**Example:**
```python
# tasks/setup_appliances.py
from core.appliance_operations import restart_appliance as core_restart

def restart_appliance(config, logger, verbose=True, **kwargs):
    """
    Task wrapper for restart_appliance.
    Provides compatibility with stage definitions.
    """
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name is required")
        return False
    
    # Call core function - all logic is there
    return core_restart(config, logger, **kwargs)
```

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
│   ├── deploy_mongo.py       # MongoDB deployment tasks
│   ├── download_supporting_files.py  # Download supporting files
│   └── ...                   # Other specific tasks
│
├── config/                    # Configuration files
│   └── config.yaml
│
└── automation.py              # Main orchestration script
```

### 2.1. Task File Organization

**IMPORTANT: Each state/stage should be in a separate file**

#### ✅ DO:
- **Create separate files for each major task/state** (e.g., `download_supporting_files.py`, `deploy_mysql.py`)
- **Keep related functions together** in the same file
- **One main entry point function per file** that orchestrates the task
- **Helper functions in the same file** if they're only used by that task

#### ❌ DON'T:
- **Don't mix multiple unrelated tasks in one file**
- **Don't put download/setup logic inside deployment tasks**
- **Don't create monolithic task files** with multiple independent stages

**Example Structure:**
```
tasks/
├── download_supporting_files.py    # Separate: Downloads files from Box
├── deploy_mysql.py                 # Separate: MySQL deployment only
├── deploy_mongo.py                 # Separate: MongoDB deployment only
└── setup_hosts.py                  # Separate: Host configuration
```

**Why:**
- Clean separation of concerns
- Easier to maintain and test
- Clear dependencies between stages
- Better code organization

### 3. Function Placement Rules

| Function Type | Location | Example |
|---------------|----------|---------|
| Command execution | `core/utils.py` | `execute_local_command()`, `execute_mysql_sql()` |
| File operations | `core/utils.py` | `read_file()`, `write_file()` |
| SSH operations | `core/ssh_client.py` | `SSHClient.execute_command()` |
| Appliance operations | `core/appliance_operations.py` | `restart_appliance()`, `backup_appliance()` |
| Appliance CLI client | `core/appliance_client.py` | `ApplianceClient.execute_command()` |
| Guardium REST API | `core/guardium_rest_api.py` | `GuardiumRestAPI.create_user()` |
| Configuration | `core/config_loader.py` | `get_machine()`, `get_custom_variable()` |
| Appliance config | `core/appliance_config_loader.py` | `get_appliance()`, `get_default_user()` |
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
7. ☐ Did I update `requirements.txt` if needed? → Yes
   - Added new Python packages (e.g., `requests` for HTTP)
   - Check imports in new code for external dependencies


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

**IMPORTANT RULE:**
- ❌ **DON'T summarize entire task history** - only report what was done in the LAST step
- ✅ **DO focus on immediate changes** - what files were modified/created in current action
- ❌ **DON'T repeat previous steps** - user already saw those confirmations
- ✅ **DO be concise** - 3-5 lines maximum for completion message

## Summary

**Golden Rule:** If a function can be used by more than one task or is a general utility, it belongs in `core/`, not in `tasks/`.

This keeps the codebase:
- ✅ DRY (Don't Repeat Yourself)
- ✅ Maintainable
- ✅ Testable
- ✅ Scalable

# Made with Bob