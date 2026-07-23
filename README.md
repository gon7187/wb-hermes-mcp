# WB Hermes MCP

MCP-сервер для кабинета продавца Wildberries на базе
[`wildberries-sdk`](https://github.com/eslazarev/wildberries-sdk). Он рассчитан
на Hermes и модели уровня GLM: названия инструментов, параметры и ошибки
сформулированы по-русски, без SDK-терминов.

Сервер предоставляет 50 инструментов основного seller-функционала:

- профиль, тарифы, карточки, цены, остатки и склады;
- FBS-заказы и поставки;
- рекламные кампании, ставки, минус-фразы, воронка и отчёты;
- баланс, финансовые документы, отзывы, вопросы и чаты.

Любая изменяющая операция работает в два шага: `wb_plan_*` только создаёт
план, а `wb_apply_change` однократно применяет его по `confirmation_id`.
Пополнение рекламного бюджета доступно только отдельным явным планом. Для
подсказки модели есть `wb_describe_operation`: он выдаёт русское назначение,
обязательные поля и безопасный пример любого инструмента.

Полный список всех 50 инструментов и их режимов работы — в
[справочнике tools](docs/tools.md).

## Локальный запуск

Нужен Python 3.12+ и токен WB со scope для нужных API.

```bash
uv sync --all-groups
export WB_API_TOKEN='…'
uv run python -m wb_mcp
```

MCP использует только `stdin`/`stdout`; диагностические сообщения идут в
`stderr`. Никогда не передавайте токен через аргументы MCP-инструментов.

## Развёртывание в Hermes

Ниже пример для уже настроенного Hermes-хоста. Токен остаётся только в
`/opt/wb-hermes-mcp/wb.env` с правами `0600`, а не в конфигурации Hermes.

```bash
rsync -az --exclude .git --exclude .venv --exclude .pytest_cache --exclude .ruff_cache \
  ./ root@<hermes-host>:/opt/wb-hermes-mcp/

ssh root@<hermes-host> '
  cd /opt/wb-hermes-mcp &&
  python3 -m venv .venv &&
  .venv/bin/pip install --upgrade pip &&
  .venv/bin/pip install --no-cache-dir --upgrade . &&
  install -m 700 deploy/run-wb-mcp.sh run-wb-mcp
'
```

Передайте токен по pipe, не сохраняя его в истории команд или конфиге Hermes:

```bash
awk -F= '$1=="WB_API_TOKEN" {print substr($0, index($0, "=") + 1); exit}' /path/to/.env \
  | ssh root@<hermes-host> 'umask 077; { printf "WB_API_TOKEN="; cat; printf "\\n"; } > /opt/wb-hermes-mcp/wb.env'
```

Зарегистрируйте сервер и проверьте его:

```bash
ssh root@<hermes-host> 'hermes mcp add wb --command /opt/wb-hermes-mcp/run-wb-mcp'
ssh root@<hermes-host> 'hermes mcp test wb'
ssh root@<hermes-host> 'systemctl restart hermes-gateway.service && systemctl is-active hermes-gateway.service'
```

Эквивалентная redacted-конфигурация находится в
[`deploy/hermes-wb-mcp.yaml.example`](deploy/hermes-wb-mcp.yaml.example).

## Проверки

```bash
uv run pytest -v
uv run ruff check --fix src tests
uv run ruff format src tests
uv run pyright src tests
shellcheck deploy/run-wb-mcp.sh
```

`evals/glm-tool-routing.json` содержит 10 русскоязычных маршрутизационных
сценариев для проверки выбора инструментов моделью.
