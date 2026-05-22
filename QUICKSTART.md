# Quick Start Guide

Get started with Machine Automation Framework in 5 minutes!

## 📦 Installation

```bash
# 1. Navigate to framework directory
cd machine_automation_framework

# 2. Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

## ⚙️ Configuration

Edit `config/config.yaml`:

```yaml
machines:
  my_server:
    host: "192.168.1.100"  # Change to your server IP
    description: "My target server"

ssh:
  username: "root"  # Change if needed
```

Set SSH password (optional):
```bash
export SSH_PASSWORD="your_password"
```

## 🎯 Create Your First Task

Create `tasks/my_tasks.py`:

```python
from core import SSHClient, get_logger, ConfigLoader

logger = get_logger("MyTasks")

def hello_world_task(config: ConfigLoader) -> bool:
    """Simple hello world task."""
    logger.info("Running hello world task...")
    
    host = config.get('machines.my_server.host')
    
    with SSHClient(host=host, username='root') as ssh:
        result = ssh.execute_command("echo 'Hello from automation!'")
        return result['rc'] == 0

def register_my_tasks(orchestrator):
    """Register tasks."""
    config = orchestrator.config
    
    orchestrator.register_task(
        task_id="001_hello_world",
        task_fn=lambda: hello_world_task(config),
        description="Hello World task"
    )
```

## 🚀 Run Automation

Edit `automation.py` - add after line 175 (before `# Run all tasks`):

```python
# Import your tasks
from tasks.my_tasks import register_my_tasks

# Register them
register_my_tasks(orchestrator)
```

Run:
```bash
python automation.py
```

## 📊 Check Status

```bash
# View execution status
python automation.py --status

# Reset and start over
python automation.py --reset
```

## 🎓 Next Steps

1. Read full [README.md](README.md) for detailed documentation
2. Check [tasks/example_tasks.py](tasks/example_tasks.py) for more examples
3. Explore [core/](core/) modules for available functionality
4. Create your own tasks in `tasks/` directory

## 💡 Common Patterns

### Multiple Commands
```python
with SSHClient(host=host, username='root') as ssh:
    commands = [
        "yum update -y",
        "yum install -y vim git",
        "systemctl restart sshd"
    ]
    results = ssh.execute_commands(commands, stop_on_error=True)
```

### File Upload
```python
with SSHClient(host=host, username='root') as ssh:
    ssh.upload_file("local_config.txt", "/etc/myapp/config.txt")
```

### Configuration Access
```python
# Get value with default
port = config.get('ssh.port', default=22)

# Get nested value
db_type = config.get('custom.database.type')

# Get entire section
machines = config.get_section('machines')
```

### Error Handling
```python
from core import retry

def risky_operation():
    # Your code here
    pass

# Retry up to 3 times with 5 second delay
result = retry(risky_operation, max_attempts=3, delay=5)
```

## 🆘 Troubleshooting

**SSH Connection Failed?**
- Check host IP in config.yaml
- Verify SSH password/key
- Test manually: `ssh root@192.168.1.100`

**Import Errors?**
- Ensure you're in `machine_automation_framework/` directory
- Check virtual environment is activated
- Verify dependencies: `pip list`

**Task Not Running?**
- Check if already completed: `python automation.py --status`
- Reset state: `python automation.py --reset`
- Check logs in `logs/` directory

---

**Ready to automate! 🚀**

For more help, see [README.md](README.md)