---
name: hermes-mcp-setup
description: Подключение и проверка MCP wb в Hermes без передачи токена модели.
---

# Hermes WB MCP setup

Сервер запускается через:

```text
/opt/wb-hermes-mcp/run-wb-mcp
```

Проверка:

```bash
hermes mcp test wb
systemctl is-active hermes-gateway.service
```

Токен хранится только в закрытом env-файле wrapper-процесса. Не добавляй его
в Hermes YAML, аргументы инструментов, cron prompts, скиллы или логи.

Автоматизации запускают локальный stdio-клиент и обращаются к явным
инструментам `wb_*`. После обновления сервера сначала проверь tool list и
read-only smoke tests, затем перезапусти gateway.
