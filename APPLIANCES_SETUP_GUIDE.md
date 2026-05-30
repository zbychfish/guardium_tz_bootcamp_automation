# Guardium Appliances Setup Guide

## Jak zarejestrować appliance w automatyce?

### Krok 1: Dodaj appliance do `config/appliances.yaml`

Edytuj plik `config/appliances.yaml` i dodaj swoje appliances:

```yaml
appliances:
  collector1:
    name: "collector1"
    ip: "10.10.9.239"
    type: "collector"
    description: "Primary Guardium Collector"
  
  cm1:
    name: "cm1"
    ip: "10.10.9.219"
    type: "cm"
    description: "Central Manager"
  
  aggregator1:
    name: "aggregator1"
    ip: "10.10.9.229"
    type: "aggregator"
    description: "Aggregator Node"
```

**Wymagane pola:**
- `name` - unikalna nazwa appliance
- `ip` - adres IP (lokalny)
- `type` - typ: `collector`, `cm`, `aggregator`, `appnode`
- `description` - opis (opcjonalny)

### Krok 2: Użyj w `config/groups.yaml`

Podaj nazwę appliance i hasło w argumentach stage:

```yaml
groups:
  setup_appliances:
    name: "Setup Appliances"
    auto_execute: false
    stages:
      - name: test_collector
        function: connect_and_show_clock
        module: tasks.setup_appliances
        args:
          appliance_name: "collector1"  # Nazwa z appliances.yaml
          password: "your_password"     # Hasło SSH
          prompt_regex: "guard\\.yourcompany\\.com>"  # Opcjonalny
      
      - name: configure_collector
        function: initial_collector_settings
        module: tasks.setup_appliances
        args:
          collector_name: "collector1"  # Nazwa z appliances.yaml
          password: "your_password"     # Hasło SSH
```

### Krok 3: Uruchom

```bash
# Test połączenia
python automation.py --group setup_appliances --stage test_collector

# Konfiguracja
python automation.py --group setup_appliances --stage configure_collector

# Cała grupa
python automation.py --group setup_appliances
```

## Typy Appliances

### collector
- **Typ:** Guardium Data Collector
- **Domyślny user:** cli
- **Domyślny prompt (unconfigured):** `guard\.yourcompany\.com>`
- **Domyślny prompt (configured):** `coll\d+\.gdemo\.com>`

### cm
- **Typ:** Central Manager
- **Domyślny user:** cli
- **Domyślny prompt:** `cm\.gdemo\.com>`

### aggregator
- **Typ:** Aggregator
- **Domyślny user:** cli
- **Domyślny prompt:** `aggregator\d*\.gdemo\.com>`

### appnode
- **Typ:** Application Node
- **Domyślny user:** cli
- **Domyślny prompt:** `appnode\d*\.gdemo\.com>`

## Parametry zadań

### connect_and_show_clock

**Wymagane:**
- `appliance_name` - nazwa z appliances.yaml
- `password` - hasło SSH

**Opcjonalne:**
- `user` - użytkownik SSH (domyślnie z typu appliance)
- `prompt_regex` - regex promptu (domyślnie z typu appliance)

### initial_collector_settings

**Wymagane:**
- `collector_name` - nazwa collectora z appliances.yaml
- `password` - hasło SSH

**Opcjonalne:**
- `user` - użytkownik SSH (domyślnie "cli")
- `prompt_regex` - regex promptu (domyślnie dla unconfigured collector)

## Przykład pełnej konfiguracji

### `config/appliances.yaml`
```yaml
appliances:
  collector1:
    name: "collector1"
    ip: "10.10.9.239"
    type: "collector"
    description: "Primary Collector"
  
  collector2:
    name: "collector2"
    ip: "10.10.9.240"
    type: "collector"
    description: "Secondary Collector"
  
  cm1:
    name: "cm1"
    ip: "10.10.9.219"
    type: "cm"
    description: "Central Manager"
```

### `config/groups.yaml`
```yaml
groups:
  setup_appliances:
    name: "Setup Appliances"
    auto_execute: false
    stages:
      # Test wszystkich appliances
      - name: test_collector1
        function: connect_and_show_clock
        module: tasks.setup_appliances
        args:
          appliance_name: "collector1"
          password: "guardium123"
      
      - name: test_collector2
        function: connect_and_show_clock
        module: tasks.setup_appliances
        args:
          appliance_name: "collector2"
          password: "guardium123"
      
      - name: test_cm
        function: connect_and_show_clock
        module: tasks.setup_appliances
        args:
          appliance_name: "cm1"
          password: "guardium123"
          prompt_regex: "cm\\.gdemo\\.com>"
      
      # Konfiguracja collectorów
      - name: configure_collector1
        function: initial_collector_settings
        module: tasks.setup_appliances
        args:
          collector_name: "collector1"
          password: "guardium123"
      
      - name: configure_collector2
        function: initial_collector_settings
        module: tasks.setup_appliances
        args:
          collector_name: "collector2"
          password: "guardium123"
```

## Prompt Regex - Przykłady

| Appliance | Prompt | Regex |
|-----------|--------|-------|
| Unconfigured collector | `guard.yourcompany.com>` | `guard\\.yourcompany\\.com>` |
| Configured collector | `coll1.gdemo.com>` | `coll1\\.gdemo\\.com>` |
| Central Manager | `cm.gdemo.com>` | `cm\\.gdemo\\.com>` |
| Aggregator | `aggregator1.gdemo.com>` | `aggregator1\\.gdemo\\.com>` |

**Uwaga:** W regex kropki muszą być escapowane: `\\.`

## Troubleshooting

### Problem: "Appliance 'xxx' not found in appliances.yaml"
**Rozwiązanie:** Sprawdź czy nazwa w `appliance_name` dokładnie odpowiada `name` w `appliances.yaml`

### Problem: "Password is required"
**Rozwiązanie:** Dodaj parametr `password` w `args` w groups.yaml

### Problem: "Timeout waiting for prompt"
**Rozwiązanie:** 
1. Sprawdź czy `prompt_regex` jest poprawny
2. Zaloguj się ręcznie przez SSH i sprawdź dokładny format promptu
3. Dodaj własny `prompt_regex` w args

### Problem: "Connection failed"
**Rozwiązanie:** Sprawdź:
- Czy IP jest poprawny w appliances.yaml
- Czy hasło jest poprawne
- Czy appliance jest dostępny przez SSH (port 22)