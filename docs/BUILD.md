# Сборка из исходников

## Что где лежит

- `src/*.py` — генерация карты (Python 3.11): слои из ванильных векторных тайлов, зоны по
  скриншотам из `zone/`, рендер тем, текстуры `.ytd`, план векторной карты.
- `src/*.cs` — установщик и утилита `rpftool` (C# 5, `csc.exe` из .NET Framework 4): чтение и
  патчинг архивов RPF7, сборка текстур и векторных тайлов на машине игрока.
- `src/checks/` — проверки собранных векторных тайлов и тест установки.
- `zone/` — скриншоты карты с отмеченными зонами (исходные данные для зон).
- `docs/images/` — картинки для README, их делает `src/docs_images.py`.

Не в репозитории (`.gitignore`): `files/` — извлечённые файлы игры, `tools/` — venv и ключи,
`build/` и `dist/` — всё сгенерированное.

## Шаги

Нужны: Windows, GTA V (Legacy), Python 3.11 с `numpy scipy opencv-python pillow fonttools
shapely mapbox-earcut`, шрифт Bahnschrift (есть в Windows 10/11), `texconv` из DirectXTex.

1. Утилита: `csc -r:System.Drawing.dll -out:build\rpftool.exe src\NovaRpf.cs src\Patcher.cs src\MapBuild.cs src\RpfTool.cs`.
   `rpftool keys <папка игры> tools\keys\aes.bin` находит ключ шифрования в `GTA5.exe` (он не хранится
   в коде), `rpftool extract tools\keys\aes.bin src\magic.dat <архив> <путь внутри> <файл>` достаёт
   из архивов игры в `files/game/` ванильные текстуры миникарты, векторные тайлы `minimap_*.ydd`
   (`files/game/minimap_ydd/`), `popzone.ipl`, `heightmap.dat`.
2. Данные (из корня проекта, `python src/<скрипт>`):
   `layers.py` → `borders.py` → `register.py` → `pins.py` → `zones.py` →
   `render.py --overlays` → `render.py` → `build_ytd.py` → `vector_plan.py` → `installer_previews.py`.
3. Проверка тайлов: `python src/checks/validate_tiles.py`.
4. Установщик: `powershell -File src\build_installer.ps1` → `dist\NovaMap_Installer.exe`.
5. Тест на копиях файлов игры (сверка с эталоном, установка, откат): `powershell -File src\checks\test_install.ps1`.
6. Картинки для README: `python src/docs_images.py`.

Рендер векторной карты в порядке отрисовки: `python src/checks/render_tiles.py <вариант> <файл> <x0> <y0> <x1> <y1> <ширина>`.

## Как устроена векторная карта

В приближении и на радаре игра рисует векторные тайлы, а не текстуры. В каждом изменённом тайле
модели суши, кварталов и дорог собираются в один буфер в фиксированном порядке, и последняя модель
несёт наши линии и подписи. Буферы воды остаются ванильными: игра перестаёт их рисовать,
если их трогать. Подробности — в начале `src/vector_plan.py`.

Всё, что должно совпадать на дальнем виде и в приближении (подписи, сетка, декор темы «Сакура»),
строится из одних и тех же многоугольников: текстура их растеризует, векторные тайлы разбивают на
треугольники (`src/textgeo.py`, `src/sakura.py`).
