# Stage Mechanism Documentation

## Overview

The stage mechanism allows you to control the execution flow of the automation framework by defining a checkpoint where the initial automated run should stop. This is particularly useful for TechZone post-deploy automation where you want some tasks to run automatically and others to be executed manually later.

## How It Works

### 1. Stage Parameter

The `stage` parameter is defined in the `custom_variables` section of `/root/machines_info.json`:

```json
{
  "custom_variables": {
    "pwd": "Guardium123!",
    "stage": "setup_remote_hana"
  }
}
```

The `stage` value should be the **task_id** of the last task you want to execute in the initial run.

### 2. Execution Modes

#### Initial Run (Automatic)
```bash
python automation.py
```
- Reads `stage` from `machines_info.json`
- Executes tasks up to and including the stage task
- Stops at the stage checkpoint
- Displays message: "To continue with remaining tasks, run: python automation.py --continue"

#### Continue Mode (Manual)
```bash
python automation.py --continue
```
- Ignores the `stage` parameter
- Executes all remaining tasks (skips already completed ones)
- Runs until all tasks are complete

#### Full Run (Override)
```bash
python automation.py --stop-at some_task_id
```
- Overrides `stage` from machines_info.json
- Stops at the specified task_id

### 3. State Management

The framework uses `state.json` to track completed tasks:
- Tasks completed in initial run are marked as completed
- `--continue` mode skips already completed tasks
- Use `--reset` to clear state and start fresh

## Usage Examples

### Example 1: Basic Stage Usage

**machines_info.json:**
```json
{
  "custom_variables": {
    "pwd": "Guardium123!",
    "stage": "setup_local_raptor"
  }
}
```

**Execution:**
```bash
# Initial run (automatic via post-deploy)
python automation.py
# Output: Executes only "setup_local_raptor", then stops

# Continue manually
python automation.py --continue
# Output: Executes all remaining tasks (setup_remote_hana, setup_remote_db2, etc.)
```

### Example 2: Multi-Machine Setup

**machines_info.json:**
```json
{
  "custom_variables": {
    "pwd": "Guardium123!",
    "stage": "setup_remote_toolnode"
  }
}
```

**Registered tasks:**
1. `setup_local_raptor`
2. `setup_remote_hana`
3. `setup_remote_db2`
4. `setup_remote_postgres`
5. `setup_remote_toolnode` ← **STAGE**
6. `install_guardium`
7. `configure_guardium`

**Execution:**
```bash
# Initial run
python automation.py
# Executes tasks 1-5, stops at setup_remote_toolnode

# Continue
python automation.py --continue
# Executes tasks 6-7
```

### Example 3: Check Status

```bash
python automation.py --status
```

**Output:**
```
================================================================================
AUTOMATION STATUS
================================================================================
Total tasks: 7
Completed: 5
Remaining: 2

Stage checkpoint: setup_remote_toolnode
  ✓ Stage reached - run with --continue to proceed

Completed tasks:
  ✓ setup_local_raptor
  ✓ setup_remote_hana
  ✓ setup_remote_db2
  ✓ setup_remote_postgres
  ✓ [STAGE] setup_remote_toolnode

Remaining tasks:
  ○ install_guardium
  ○ configure_guardium
================================================================================
```

## Determining Stage Value

### Method 1: List All Tasks

Run with `--status` before any execution:
```bash
python automation.py --status
```

This shows all registered task IDs.

### Method 2: Check Logs

Run the automation and check the logs:
```bash
python automation.py 2>&1 | grep "Registered task"
```

### Method 3: Read automation.py

Look for `orchestrator.register_task()` calls:
```python
orchestrator.register_task(
    task_id="setup_local_raptor",  # ← This is the task_id
    task_fn=...,
    description="..."
)
```

## Common Stage Values

Based on typical automation workflow:

| Stage Value | Description | Use Case |
|-------------|-------------|----------|
| `setup_local_raptor` | Stop after configuring local machine | Minimal initial setup |
| `setup_remote_hana` | Stop after first remote machine | Test connectivity |
| `setup_remote_toolnode` | Stop after all machine setup | Complete infrastructure setup |
| (no stage) | Run all tasks | Full automation |

## TechZone Manifest Integration

### Manifest Example

```yaml
post_deploy:
  jobs:
    - name: prepare-raptor
      tasks:
        - name: extract-machines-info
          playbook: "playbooks/post-deploy/extract-machines-info2.yml"
          variables:
            pwd: "Guardium123!"
            stage: "setup_remote_toolnode"  # ← Define stage here
        
        - name: setup-environment
          script: "scripts/setup-git-venv.sh"
        
        - name: run-automation
          script: "scripts/run-automation.sh"
```

### Workflow

1. **TechZone deploys VMs**
2. **extract-machines-info** playbook:
   - Collects VM information
   - Saves `pwd` and `stage` to `/root/machines_info.json`
3. **setup-environment** script:
   - Clones automation repository
   - Creates virtual environment
4. **run-automation** script:
   - Executes `python automation.py`
   - Reads `stage` from machines_info.json
   - Runs tasks up to stage checkpoint
   - Stops automatically
5. **Manual continuation** (later):
   - SSH to raptor
   - Run `python automation.py --continue`
   - Completes remaining tasks

## Advanced Usage

### Override Stage from Command Line

```bash
# Ignore stage from JSON, stop at different task
python automation.py --stop-at setup_remote_db2
```

### Reset and Re-run

```bash
# Clear all completed tasks
python automation.py --reset

# Run again from beginning
python automation.py
```

### Dry Run (Check What Will Execute)

```bash
# Check status without executing
python automation.py --status
```

## Error Handling

### Invalid Stage Task ID

If the stage task_id doesn't exist:

```bash
python automation.py
```

**Output:**
```
[ERROR] Stage task 'invalid_task' not found in registered tasks
[ERROR] Available task IDs: setup_local_raptor, setup_remote_hana, ...
```

**Solution:** Update the `stage` value in machines_info.json to a valid task_id.

### Stage Already Completed

If you run the initial automation again after stage is reached:

```bash
python automation.py
```

**Output:**
```
⏭  Skipping (already completed): setup_local_raptor
⏭  Skipping (already completed): setup_remote_hana
...
✓ Reached stage checkpoint: setup_remote_toolnode
```

The framework skips already completed tasks automatically.

## Best Practices

1. **Choose Meaningful Stage Points**
   - End of infrastructure setup
   - Before application installation
   - After critical configuration

2. **Document Stage Values**
   - Add comments in manifest
   - Update documentation when adding tasks

3. **Test Stage Behavior**
   - Test initial run stops at correct point
   - Test continue mode completes remaining tasks
   - Verify state.json tracks progress correctly

4. **Use Status Command**
   - Check progress: `python automation.py --status`
   - Verify stage checkpoint reached
   - See remaining tasks

5. **Reset When Needed**
   - Use `--reset` for clean re-runs
   - Useful for testing and debugging

## Troubleshooting

### Stage Not Working

**Problem:** Automation runs all tasks despite stage parameter.

**Possible Causes:**
1. Stage value not in machines_info.json
2. Using `--continue` flag
3. Stage task_id doesn't match registered task

**Solution:**
```bash
# Check machines_info.json
cat /root/machines_info.json | jq '.custom_variables.stage'

# Check registered tasks
python automation.py --status

# Verify task_id matches exactly
```

### Continue Mode Not Working

**Problem:** `--continue` doesn't execute remaining tasks.

**Possible Causes:**
1. All tasks already completed
2. State file corrupted

**Solution:**
```bash
# Check status
python automation.py --status

# If needed, reset state
python automation.py --reset

# Run again
python automation.py --continue
```

## Implementation Details

### Code Flow

1. **Parse Arguments**
   ```python
   parser.add_argument("--continue", dest="continue_mode", action="store_true")
   ```

2. **Read Stage from JSON**
   ```python
   stage = orchestrator.config.get_custom_variable('stage')
   ```

3. **Determine Stop Point**
   ```python
   stop_at_task = args.stop_at if args.stop_at else stage
   ```

4. **Execute with Mode**
   ```python
   orchestrator.run_all_tasks(
       stop_at=stop_at_task,
       continue_mode=args.continue_mode
   )
   ```

5. **Check Stop Condition**
   ```python
   if not continue_mode and stop_at and task_id == stop_at:
       logger.info(f"✓ Reached stage checkpoint: {stop_at}")
       return True
   ```

### State Persistence

The framework uses `state.json` to persist completed tasks:

```json
{
  "completed_tasks": [
    "setup_local_raptor",
    "setup_remote_hana",
    "setup_remote_toolnode"
  ],
  "last_updated": "2026-05-23T10:30:00Z"
}
```

This ensures:
- Tasks aren't re-executed unnecessarily
- Continue mode knows where to resume
- Progress is preserved across runs

# Made with Bob