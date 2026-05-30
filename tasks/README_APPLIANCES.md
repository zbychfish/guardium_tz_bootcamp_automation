# Setup Appliances Tasks

Tasks for configuring Guardium appliances via SSH CLI.

## Available Tasks

### `connect_and_show_clock`
Test connectivity and display system clock.

**Args:**
- `appliance_ip`: IP address of appliance

**Example:**
```python
{
    "function": connect_and_show_clock,
    "args": {"appliance_ip": "10.10.9.239"}
}
```

### `initial_collector_settings`
Configure initial collector settings (timezone, NTP, purge).

**Args:**
- `collector_ip`: IP address of collector

**Example:**
```python
{
    "function": initial_collector_settings,
    "args": {"collector_ip": "10.10.9.239"}
}
```

## Configuration Requirements

Appliances must be defined in `config/groups.yaml` with:
- `host`: IP address
- `user`: SSH username (default: "cli")
- `password`: SSH password
- `prompt_regex`: Regex pattern matching CLI prompt

**Example:**
```yaml
machines:
  collector:
    host: "10.10.9.239"
    user: "cli"
    password: "your_password"
    prompt_regex: "guard\\.yourcompany\\.com>"
```

## Usage

See `example_setup_appliances.py` for complete examples.

**Quick start:**
```bash
python automation.py --group your_group --stage setup_appliances_test