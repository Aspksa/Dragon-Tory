from __future__ import annotations

from typing import Any

RELEASE_NOTES: dict[str, dict[str, Any]] = {
    "00.00.27": {
        "title": "Табель и жизненный цикл гаража",
        "modules": [
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.05.00",
                "changes": [
                    "Предупреждения об истекающих и просроченных страховках автопарка.",
                ],
            },
            {
                "id": "garage",
                "title": "Гараж",
                "version": "01.03.00",
                "changes": [
                    "Летняя и зимняя нормы ГСМ.",
                    "Размеры летних и зимних шин.",
                    "Страховой полис, компания и даты действия.",
                    "Предупреждение за 15 дней и отметка просроченной страховки.",
                ],
            },
            {
                "id": "timesheet",
                "title": "Табель",
                "version": "01.05.00",
                "changes": [
                    "Производственные календари РФ 2026/2027.",
                    "Месячная сетка Т-13-подобного вида.",
                    "Ручные коды ОТ и Б.",
                    "Работа в выходной день из служебных записок.",
                    "Проверка конфликтов между отсутствием и работой в выходной.",
                ],
            },
        ],
    },
    "00.00.28": {
        "title": "Служебные записки: изучение, сортировка и доказательства",
        "modules": [
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.05.00",
                "changes": [
                    "Карточка «Основные факты» с подтверждающими фрагментами.",
                    "Отдельное хранение даты записки и дат событий.",
                    "Автосортировка Проект / Документы / Год / Служебные записки / Тема.",
                    "Год из даты записки; fallback по названию с пометкой проверки.",
                    "Темы определяются прежде всего по содержанию.",
                    "Просьба отделяется от подтверждённого результата.",
                    "Полные копии связываются по SHA-256, возможные версии сохраняются отдельно.",
                    "Шаблоны складываются в Проект / Шаблоны / Служебные записки.",
                    "AI-изучение и проектная память через Guardian.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.08.00",
                "changes": [
                    "Автоматическое создание только реально используемых годовых и тематических папок.",
                    "Перемещение оригинала без изменения его байтов.",
                    "Связи копий и возможных версий служебных записок.",
                ],
            },
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "01.07.00",
                "changes": [
                    "Факты служебных записок сохраняются в памяти проекта через Memory Intake и Guardian.",
                    "Повторная полная копия не создаёт новую запись фактов.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "История обновлений показывает изменения по модулям, а не только список файлов.",
                    "Добавлены release notes для 00.00.27, включая Гараж и Табель.",
                ],
            },
        ],
    },
    "00.00.29": {
        "title": "Cognitive Core: Memory v5 hybrid retrieval",
        "modules": [
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "02.00.00",
                "changes": [
                    "Добавлен локальный SQLite FTS5-индекс памяти с автоматическим backfill.",
                    "Полнотекстовый поиск выполняется отдельно от окна важности и свежести.",
                    "Hybrid recall объединяет FTS5 и существующий semantic/reranking канал.",
                    "Личная и проектная память остаются жёстко изолированными.",
                    "Health-report показывает доступность FTS5 и число индексированных записей.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.06.00",
                "changes": [
                    "Диагностика памяти подготовлена к отображению состояния lexical index.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.05.00",
                "changes": [
                    "Правила 00.00.28 сохранены без регрессии при обновлении Cognitive Core.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.08.00",
                "changes": [
                    "Документы и существующая структура диска совместимы с Memory v5.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "Обновление до 00.00.29 сохраняет локальные данные и автоматически создаёт FTS5-индекс.",
                ],
            },
        ],
    },
    "00.00.30": {
        "title": "Cognitive Core II: рабочая, эпизодическая и временная память",
        "modules": [
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "02.01.00",
                "changes": [
                    "Добавлена эпизодическая память успешного результата: задача пользователя и итог Тоору.",
                    "Добавлены observed_at, event_at, valid_from и valid_to для временной истины.",
                    "Добавлена таблица evidence/provenance с источником, документом, страницей, фрагментом и уверенностью.",
                    "Memory Intelligence и Guardian сохраняют временные поля, а не теряют их при AI-анализе.",
                    "Структурированный Memory Intake автоматически прикрепляет происхождение записи.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.07.00",
                "changes": [
                    "Cognitive Core подготовлен к наблюдению за working/episodic/temporal memory.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.05.00",
                "changes": [
                    "Факты, поступающие через Memory Intake, получают provenance без изменения оригиналов записок.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.08.00",
                "changes": [
                    "Документные ссылки могут использоваться как доказательства долговременной памяти.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "SQLite-миграция 00.00.30 добавляет новые поля и evidence-таблицу без потери локальных данных.",
                ],
            },
        ],
    },
    "00.00.31": {
        "title": "Cognitive Core III: Reasoning & Truth Engine",
        "modules": [
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "02.02.00",
                "changes": [
                    "Добавлен детерминированный trust-score по confidence, evidence, feedback, времени, поддержке и конфликтам.",
                    "Факты с одинаковым key и непересекающимися периодами больше не считаются ложным противоречием.",
                    "Добавлены temporal_successor и temporal_predecessor связи.",
                    "Recall расширяет кандидатов через граф RELATED/SUPPORTS/SUMMARIZES и временные связи.",
                    "Финальный reranker учитывает graph_score и truth_score.",
                    "Добавлен API /v1/memory/{memory_id}/truth.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.08.00",
                "changes": [
                    "Контекст памяти теперь содержит truth-score, подготовленный для визуализации доверия и конфликтов.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.05.00",
                "changes": [
                    "Evidence из служебных записок участвует в оценке доверия факта.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.08.00",
                "changes": [
                    "Документные доказательства используются Truth Engine при оценке памяти.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "00.00.31 не требует разрушительной миграции базы и сохраняет данные 00.00.30.",
                ],
            },
        ],
    },
    "00.00.32": {
        "title": "Cognitive Core IV: Planner, Verifier & Experience Learning",
        "modules": [
            {
                "id": "reasoning",
                "title": "Мышление Тоору",
                "version": "01.00.00",
                "changes": [
                    "Сложные задачи получают внутренний исполняемый план до основного ответа.",
                    "Result Verifier проверяет ответ по исходной цели, критериям успеха и доступному контексту.",
                    "При исправимой ошибке Verifier может вернуть полностью исправленный ответ.",
                    "Простые сообщения проходят без Planner/Verifier, чтобы не увеличивать задержку и стоимость.",
                    "Experience Learning анализирует только подтверждённые результаты с высоким verification score.",
                    "Повторяемое правило формируется только после минимум трёх похожих verified episodes и проходит Guardian.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.09.00",
                "changes": [
                    "Операции reasoning_plan, result_verify и experience_learning видны через существующую observability-трассировку.",
                ],
            },
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "02.02.00",
                "changes": [
                    "Проверенные эпизоды получают тег verified-outcome и используются как доказанный опыт.",
                    "Кандидаты experience-rule не применяются напрямую и проходят Memory Guardian.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.05.00",
                "changes": [
                    "Существующая документная память остаётся совместимой с Cognitive Core IV.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.08.00",
                "changes": [
                    "Фрагменты документов могут участвовать в планировании и проверке как недоверенный контекст.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "00.00.32 не требует разрушительной миграции локальной базы.",
                ],
            },
        ],
    },
    "00.00.33": {
        "title": "Document Intelligence v2: структурный анализ и доказательства",
        "modules": [
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.09.00",
                "changes": [
                    "Большие документы анализируются chunk-first без ограничения первыми 250000 символами.",
                    "Для анализа сохраняются structure, checks и evidence с chunk/page/table/cell.",
                    "Добавлены проверки итоговых сумм, НДС, основных реквизитов и подозрительных AI-инструкций в тексте.",
                    "Смысловое сравнение версий использует representative sampling по всему документу.",
                    "Локальный diff показывает добавленные/удалённые структурированные факты с доказательствами.",
                ],
            },
            {
                "id": "contracts",
                "title": "Договоры",
                "version": "01.06.00",
                "changes": [
                    "Проверяются контрагент, номер, даты, сроки, суммы и документные evidence.",
                ],
            },
            {
                "id": "invoice_offers",
                "title": "Счета-оферты",
                "version": "01.05.00",
                "changes": [
                    "Добавлены кандидаты итоговой суммы, НДС и предупреждение об отсутствии ключевых реквизитов.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.06.00",
                "changes": [
                    "Основные факты получают более точную структурную привязку к исходному документу.",
                ],
            },
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "02.03.00",
                "changes": [
                    "Document evidence расширен полями table_ref, cell_ref, chunk_no и evidence_hash.",
                    "Изучение документа прикрепляет точные доказательства к долговременной памяти через Guardian.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "Миграции 00.00.33 добавляют новые evidence/analysis поля без удаления существующих локальных данных.",
                ],
            },
        ],
    },
    "00.00.34": {
        "title": "Cognitive Core V: Grey Matter",
        "modules": [
            {
                "id": "grey_matter",
                "title": "Серое вещество",
                "version": "01.00.00",
                "changes": [
                    "Добавлен локальный semantic embedding provider FastEmbed с multilingual-моделью и безопасным hash fallback.",
                    "Иерархическая память строит PART_OF связи от фактов/эпизодов/задач к консолидационным summary.",
                    "Entity Resolution хранит алиасы и SAME_ENTITY связи без смешивания personal/project scope.",
                    "Causal Memory хранит цепочки причина → проблема → действие → результат.",
                    "Uncertainty Engine различает низкую/среднюю/высокую неопределённость и показывает альтернативные конфликтующие факты.",
                    "Memory Consolidation v2 запускает фоновый Grey Matter sleep-cycle без бесконтрольного создания новых summary.",
                    "Goal & Task Memory поддерживает прогресс цели, task state и DEPENDS_ON зависимости.",
                    "Multi-hop retrieval проходит до двух шагов в обычном recall и до шести шагов через Grey Matter API.",
                    "Source Reliability обучается на подтверждениях/опровержениях источника и участвует в Truth Engine.",
                    "Correction Learning сохраняет уроки из явных исправлений пользователя через Guardian.",
                    "Counterfactual Verifier проверяет альтернативные объяснения, контрфактический сценарий и явную uncertainty.",
                    "Skill Memory хранит повторяемые проверенные рабочие процедуры как отдельный защищённый тип skill.",
                ],
            },
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "03.00.00",
                "changes": [
                    "Добавлены типы skill и lesson и новые графовые связи причинности, сущностей, целей и исправлений.",
                    "Truth Engine учитывает обучаемую надёжность источника.",
                    "Recall выдаёт uncertainty_score и использует двухшаговое typed graph expansion.",
                    "SQLite получил таблицы source reliability и entity aliases с обратной совместимостью.",
                ],
            },
            {
                "id": "reasoning",
                "title": "Мышление Тоору",
                "version": "02.00.00",
                "changes": [
                    "Result Verifier получил alternative_explanations, counterfactual_checks и uncertainty.",
                    "Experience Learning создаёт skill-кандидаты, которые требуют Guardian review.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.10.00",
                "changes": [
                    "Реестр модулей теперь содержит отдельный Grey Matter слой для будущей визуализации мозга.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.09.00",
                "changes": [
                    "Document Intelligence v2 остаётся совместимым с Grey Matter и точным provenance.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.06.00",
                "changes": [
                    "Правила служебных записок и проектная память сохраняются без изменений.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "00.00.34 добавляет только совместимые SQLite-таблицы и не удаляет существующую память.",
                ],
            },
        ],
    },
    "00.00.35": {
        "title": "Cognitive Core VI: Adaptive Grey Matter",
        "modules": [
            {
                "id": "grey_matter",
                "title": "Серое вещество",
                "version": "02.00.00",
                "changes": [
                    "Recall автоматически выбирает lexical, semantic, graph, temporal, causal или balanced стратегию.",
                    "Temporal retrieval поддерживает as_of и переоценивает truth на исторический момент.",
                    "Truth-feedback сохраняет predicted trust и строит Brier score / calibration error.",
                    "Противоречивые факты объединяются в кластеры с trust-gap и признаком unresolved.",
                    "Причинные связи проверяют порядок событий и обучают вес CAUSES по подтверждениям.",
                    "Entity merge проходит proposal → Guardian → finalize и не склеивает сущности молча.",
                    "Adaptive forgetting укрепляет полезную память, ослабляет слабую и архивирует только безопасные типы.",
                    "Фоновый sleep-cycle запускает conservative adaptive forgetting автоматически.",
                    "Добавлен retrieval benchmark evaluator и scale-runner для 1k/10k/100k записей.",
                ],
            },
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "03.01.00",
                "changes": [
                    "MemorySearch получил strategy и as_of; MemoryRecallHit показывает фактически выбранную стратегию.",
                    "Reranker использует разные профили весов для lexical/semantic/graph/temporal/causal запросов.",
                    "Graph expansion выбирает семейство связей по стратегии запроса.",
                    "SQLite хранит truth-feedback calibration events и проверяет их целостность в health-report.",
                    "Добавлено audited archive_memory для безопасного adaptive forgetting.",
                ],
            },
            {
                "id": "reasoning",
                "title": "Мышление Тоору",
                "version": "02.00.00",
                "changes": [
                    "Planner и Verifier автоматически получают более релевантный контекст через Adaptive Recall.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.09.00",
                "changes": [
                    "Document Intelligence v2 и структурный provenance остаются совместимыми с Adaptive Grey Matter.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.06.00",
                "changes": [
                    "Правила обработки служебных записок не меняются и продолжают использовать изолированную проектную память.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "00.00.35 добавляет совместимую SQLite-таблицу truth-feedback без удаления существующей памяти.",
                ],
            },
        ],
    },
    "00.00.36": {
        "title": "Cognitive Core VII: Adaptive Reasoning Router",
        "modules": [
            {
                "id": "reasoning",
                "title": "Мышление Тоору",
                "version": "03.00.00",
                "changes": [
                    "Reasoning Router автоматически выбирает Chain, Tree или Hybrid без пользовательского переключателя.",
                    "Chain остаётся быстрым путём и для простого запроса использует один основной AI-вызов.",
                    "Tree запускается при высокой сложности, нескольких противоречиях или высокой uncertainty памяти.",
                    "Hybrid сначала выполняет линейный путь и разворачивает дерево только после слабого Result Verifier.",
                    "Tree ограничен 3–5 альтернативными ветвями и не запускает бесконечные циклы.",
                    "Tree хранит только краткие проверяемые гипотезы, доказательства, риски и confidence, а не скрытую пошаговую цепочку мыслей.",
                    "После Hybrid-эскалации итог синтезируется и повторно проверяется Result Verifier.",
                    "Режим reasoning сохраняется в episodic memory как metadata/tag для последующего обучения.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.11.00",
                "changes": [
                    "Observability получает событие reasoning_route с автоматически выбранным режимом и причинами.",
                    "Кнопки или ручной выбор Chain/Tree/Hybrid не добавляются.",
                ],
            },
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "03.01.00",
                "changes": [
                    "Reasoning Router переиспользует уже найденные context hits и не запускает повторный semantic recall только ради выбора режима.",
                    "Uncertainty и CONTRADICTS из релевантной памяти участвуют в автоматическом выборе глубины мышления.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.09.00",
                "changes": [
                    "Document Intelligence v2 остаётся совместимым и может автоматически повышать глубину reasoning через противоречивый контекст.",
                ],
            },
            {
                "id": "memos",
                "title": "Служебные записки",
                "version": "01.06.00",
                "changes": [
                    "Правила обработки служебных записок не меняются; сложные случаи могут автоматически перейти в Hybrid/Tree.",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.05.00",
                "changes": [
                    "00.00.36 не требует разрушительной миграции SQLite.",
                ],
            },
        ],
    },
    "00.00.37": {
        "title": "Windows startup hardening",
        "modules": [
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.06.00",
                "changes": [
                    "Backend Dragon Tory запускается и проходит /health до проверки необязательных Tesseract OCR и LibreOffice.",
                    "Зависший или долгий winget install LibreOffice больше не мешает открыть интерфейс Тоору.",
                    "bootstrap.ps1 оставлен ASCII-safe для совместимости с Windows PowerShell 5.1 и устранения mojibake в launcher log.",
                    "Переменная TOORU_SKIP_DOCUMENT_ENGINES=1 по-прежнему позволяет полностью пропустить автоматическую проверку системных движков.",
                ],
            },
        ],
    },
    "00.00.38": {
        "title": "Cognitive Core VIII: Adaptive Learning & Proactive Intelligence",
        "modules": [
            {
                "id": "cognition",
                "title": "Cognitive Core VIII",
                "version": "01.00.00",
                "changes": [
                    "Добавлена отдельная SQLite-база когнитивного опыта, policy, рабочего графа и проактивных инсайтов без смешивания с личной/проектной памятью.",
                    "Reasoning outcomes сохраняют только технические метрики качества: режим, complexity, uncertainty, verifier score, AI-вызовы, длительность и эскалацию.",
                    "Bounded self-learning аккуратно корректирует пороги Chain/Hybrid/Tree только после достаточного числа проверенных эпизодов и в жёстко ограниченных диапазонах.",
                    "Metacognitive Control оценивает достаточность доказательств, uncertainty и давление противоречий и может автоматически повысить глубину reasoning.",
                    "Рабочий граф связывает людей, автомобили, документы, контрагентов, деньги, события, работы и существующие междокументные связи.",
                    "Режим «Тоору сама заметила» автоматически ищет просроченные страховки, дубли идентификаторов, конфликт VIN↔госномер, ошибки документов, прошедшие сроки, несоответствия контрагентов, счета без найденного договора, повторные номера, частые ремонты, скачки стоимости строк запчастей/работ и подозрительные суммы.",
                    "Проактивные инсайты имеют severity, confidence, evidence, дедупликацию и жизненный цикл open / acknowledged / resolved / dismissed.",
                    "Явные исправления пользователя превращаются в LESSON-кандидаты только через Memory Guardian.",
                    "Cognition Automation анализирует разрешённые необработанные документы, обучает policy, перестраивает граф и повторно проверяет аномалии; загрузки и изменения справочников запускают цикл событийно с debounce.",
                ],
            },
            {
                "id": "reasoning",
                "title": "Мышление Тоору",
                "version": "04.00.00",
                "changes": [
                    "Adaptive Reasoning Router применяет обучаемую bounded policy перед каждым запросом.",
                    "Метакогнитивная оценка может эскалировать Chain → Hybrid → Tree при недостатке доказательств, высокой uncertainty или противоречиях.",
                    "После выполнения сохраняются outcome-метрики для последующего безопасного обучения маршрутизатора.",
                ],
            },
            {
                "id": "memory",
                "title": "Память Тоору",
                "version": "03.02.00",
                "changes": [
                    "Пользовательские исправления сохраняются как тип LESSON через Guardian.",
                    "Когнитивная телеметрия хранится отдельно от содержательной долговременной памяти.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.12.00",
                "changes": [
                    "Cognitive Core VIII появился отдельным узлом системного мозга.",
                    "На главной автоматически отображаются состояние когнитивного цикла и свежие проактивные сигналы «Тоору заметила».",
                ],
            },
            {
                "id": "updater",
                "title": "Обновление",
                "version": "01.06.00",
                "changes": [
                    "00.00.38 добавляет новую cognition SQLite-базу без разрушительных изменений существующих memory/cloud/chat данных.",
                ],
            },
        ],
    },
    "00.00.39": {
        "title": "Cognitive Core IX: Self-Diagnostics & Machine Report",
        "modules": [
            {
                "id": "cognition",
                "title": "Cognitive Core IX",
                "version": "02.00.00",
                "changes": [
                    "Добавлен слой Self-Diagnostics & Explainability поверх Cognitive Core VIII без экспорта hidden chain-of-thought.",
                    "Машинный отчёт связывает reasoning policy, cognition graph/insights, Grey Matter capabilities, Memory health, Guardian, автоматики, AI runtime и observability в один снимок.",
                    "Диагностические findings автоматически поднимают критичные состояния: fatal document study, degraded AI study, Guardian dead-letter, Memory health и ошибки фоновых циклов.",
                ],
            },
            {
                "id": "diagnostics",
                "title": "Самодиагностика / Машинный отчёт",
                "version": "01.00.00",
                "changes": [
                    "В Настройках появилась кнопка скачивания JSON support snapshot.",
                    "Отчёт содержит версии, конфигурацию без секретов, БД/health, pipeline contracts, document status/provenance/activity, AI Contract, reasoning outcomes, cognition, observability и update state.",
                    "Тексты документов, сообщения чатов, API-ключи, токены, пароли и скрытые рассуждения в отчёт не попадают.",
                    "Для каждого документа вычисляется состояние studied / degraded / failed / analyzed / pending и сохраняются последние технические события.",
                ],
            },
            {
                "id": "drive",
                "title": "Мой диск",
                "version": "01.10.00",
                "changes": [
                    "Полный сбой изучения документа через чат теперь сохраняет chat_document_study_failed в provenance и observability.",
                    "После fatal study failure исходный файл остаётся доступен, а cognition получает фоновый debounce-trigger для локальной повторной диагностики.",
                ],
            },
            {
                "id": "dashboard",
                "title": "Главная / Системный мозг",
                "version": "01.13.00",
                "changes": [
                    "Registry показывает Cognitive Core IX и новый модуль самодиагностики.",
                ],
            },
        ],
    },
}


def release_notes_for(version: str | None) -> dict[str, Any] | None:
    if not version:
        return None
    normalized = version.strip()
    if normalized.count(".") == 2:
        parts = normalized.split(".")
        try:
            normalized = ".".join(f"{int(part):02d}" for part in parts)
        except ValueError:
            pass
    note = RELEASE_NOTES.get(normalized)
    if note is None:
        return None
    return {
        "version": normalized,
        "title": note["title"],
        "modules": [
            {
                **module,
                "changes": list(module.get("changes") or []),
            }
            for module in note["modules"]
        ],
    }
