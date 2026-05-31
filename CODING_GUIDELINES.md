# Coding Guidelines - Quick Reference

## 🚫 NEVER DO

1. **Don't touch documentation** unless explicitly asked (README.md, existing docs)
2. **Don't delete commented code** - it's temporarily disabled, not obsolete
3. **Don't duplicate code** - extract to `core/` if used in multiple places
4. **Don't create utilities in `tasks/`** - they belong in `core/`
5. **Don't mix unrelated tasks** in one file - separate concerns

## ✅ ALWAYS DO

1. **Extract reusable code to `core/`** - if used 2+ times, move it
2. **Keep tasks thin** - call core functions, minimal logic
3. **Pass `verbose` parameter** through entire call chain
4. **One task per file** - clear separation of concerns
5. **Export core functions** in `core/__init__.py`

## 📁 File Structure

```
core/                           # Reusable components
├── utils.py                   # General utilities
├── logger.py                  # Logging
├── ssh_client.py             # SSH operations
├── appliance_operations.py   # Appliance ops (restart, configure)
├── appliance_client.py       # Appliance CLI client
├── guardium_rest_api.py      # REST API operations
├── config_loader.py          # Config management
├── appliance_config_loader.py # Appliance configs
├── state_manager.py          # State tracking
└── __init__.py               # Exports

tasks/                         # Task-specific logic
├── setup_hosts.py
├── deploy_mysql.py
├── setup_appliances.py
└── ...
```

## 🎯 Function Placement

| Type | Location | Example |
|------|----------|---------|
| General utilities | `core/utils.py` | `execute_local_command()` |
| Appliance operations | `core/appliance_operations.py` | `restart_appliance()` |
| REST API | `core/guardium_rest_api.py` | `create_user()` |
| SSH operations | `core/ssh_client.py` | `execute_command()` |
| Task logic | `tasks/*.py` | `setup_hosts_locally()` |

## 🔄 DRY Principle

**When you see repeated code:**

```python
# ❌ BAD - Duplicated in multiple tasks
def restart_appliance(...):
    # 150 lines
    pass

# ✅ GOOD - Once in core, used everywhere
# core/appliance_operations.py
def restart_appliance(...):
    # 150 lines
    pass

# tasks/setup_appliances.py
from core.appliance_operations import restart_appliance
```

## 📝 Task File Pattern

```python
#!/usr/bin/env python3
from typing import Optional
from core.appliance_operations import restart_appliance as core_restart

def restart_appliance(config, logger, verbose=True, **kwargs):
    """Thin wrapper - calls core function"""
    if not kwargs.get('appliance_name'):
        logger.error("appliance_name required")
        return False
    
    return core_restart(config, logger, **kwargs)
```

## 🔍 Verbose Mode

```python
# Always accept and pass verbose parameter
def my_task(logger, verbose: bool = True):
    if verbose:
        logger.info("Detailed info")
    
    result = core_function(logger, verbose=verbose)
    return result
```

## 📊 Logging

```python
# Concise (default)
➤  task_name
✓  task_name

# Verbose (--verbose)
➤  Running: task_name
   Description: Full description
✓  Completed: task_name
```

## 🔧 When to Create Core Module

Create new `core/` module when:
- ✅ 3+ related functions for specific domain
- ✅ Functions reusable across tasks
- ✅ Complex logic warrants separation
- ✅ Domain has own patterns/structures

Examples: `appliance_operations.py`, `database_operations.py`

## ✉️ Completion Messages

**Keep SHORT and FOCUSED:**

```
✅ GOOD:
Added restart_appliance() to core/appliance_operations.py
- Extracted from tasks/setup_appliances.py
- Updated imports in 3 task files

❌ BAD:
I have successfully completed the refactoring of the restart
functionality by moving it from tasks to core and updating all
the imports and also testing it and... [10 more lines]
```

**Rules:**
- 1 line summary
- 3-5 bullet points max
- No task history repetition
- Focus on current changes only

## 🎯 Golden Rules

1. **Reusable → `core/`** - If used 2+ times, extract it
2. **Task-specific → `tasks/`** - Business logic stays in tasks
3. **Thin wrappers** - Tasks call core, add minimal logic
4. **DRY** - Don't Repeat Yourself
5. **Separate concerns** - One task per file

## 📋 Quick Checklist

Before committing:
- ☐ Reusable code in `core/`?
- ☐ Exported in `core/__init__.py`?
- ☐ No code duplication?
- ☐ `verbose` parameter passed?
- ☐ One task per file?
- ☐ Imports from `core`?

# Made with Bob