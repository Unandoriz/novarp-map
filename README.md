# novarp-map

Кастомная карта GTA V для RP-сервера NOVA RP (RAGE:MP): большая карта в меню паузы и радар.
Пять тем (тёмная, светлая, зима, хэллоуин, сакура), зоны охоты, пунктир границ городов,
по желанию — подписи районов и дорог и сетка квадратов 1×1 км. Ставится установщиком
`NovaMap_Installer.exe`, который патчит архивы игры (`update.rpf`, `x64e.rpf`) и умеет
откатывать их байт в байт. Инструкция для игроков — [dist/README.txt](dist/README.txt).

## Что в репозитории

- `src/*.py` — генерация карты (Python 3.11): слои из ванильных векторных тайлов, зоны по
  скриншотам из `zone/`, рендер тем, текстуры `.ytd`, план векторной карты.
- `src/*.cs` — установщик и утилита `rpftool` (C# 5, `csc.exe` из .NET Framework 4):
  RPF7/NG-шифрование (по коду CodeWalker, MIT), сборка текстур и векторных тайлов на машине игрока.
- `src/checks/` — проверки собранных векторных тайлов и их рендер в порядке отрисовки.
- `zone/` — скриншоты карты с отмеченными зонами охоты (исходные данные для зон).

Не в репозитории (`.gitignore`): `files/` — извлечённые файлы игры, `tools/` — venv и ключи,
`build/` и `dist/` — всё сгенерированное.

## Сборка

Нужны: Windows, GTA V (Legacy), Python 3.11 с `numpy scipy opencv-python pillow fonttools
shapely mapbox-earcut`, шрифт Bahnschrift (есть в Windows 10/11).

1. Утилита: `csc -r:System.Drawing.dll -out:build\rpftool.exe src\NovaRpf.cs src\Patcher.cs src\MapBuild.cs src\RpfTool.cs`.
   `rpftool keys <папка игры> tools\keys\aes.bin` находит ключ шифрования в `GTA5.exe` (он не хранится
   в коде), `rpftool extract tools\keys\aes.bin src\magic.dat <архив> <путь внутри> <файл>` достаёт из архивов игры в `files/game/` ванильные текстуры миникарты,
   векторные тайлы `minimap_*.ydd` (`files/game/minimap_ydd/`), `popzone.ipl`, `heightmap.dat`.
2. Данные (из корня проекта, `python src/<скрипт>`):
   `layers.py` → `borders.py` → `register.py` → `pins.py` → `zones.py` →
   `render.py --overlays` → `render.py` → `build_ytd.py` → `vector_plan.py` → `installer_previews.py`.
3. Проверки: `python src/checks/validate_tiles.py`, сверка C# с эталоном —
   `rpftool vectest … build\vector_expected\<вариант> files\game\minimap_ydd`.
4. Установщик: `powershell -File src\build_installer.ps1` → `dist\NovaMap_Installer.exe`.
5. Тест на копиях файлов игры (установка, сверка с эталоном, откат): `powershell -File src\checks\test_install.ps1`.

## Как устроена векторная карта

В приближении и на радаре игра рисует векторные тайлы, а не текстуры. В каждом изменённом тайле
модели суши, кварталов и дорог собираются в один буфер в фиксированном порядке, и последняя модель
несёт наши линии и подписи. Буферы воды остаются ванильными: игра перестаёт их рисовать,
если их трогать. Подробности — в начале `src/vector_plan.py`.
