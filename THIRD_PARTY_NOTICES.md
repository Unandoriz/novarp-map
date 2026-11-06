# Сторонний код и данные

## Шифрование архивов GTA V

Шифрование в установщике основано на файлах `GTACrypto.cs` и `GTAKeys.cs`
из [CodeWalker](https://github.com/dexyfex/CodeWalker), которые распространяются на этих условиях:

```
Copyright(c) 2015 Neodymium

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Формат архивов RPF и `magic.dat`

Работа с форматом RPF в установщике сделана по образцу `RpfFile.cs` из CodeWalker.
Файл `magic.dat` внутри установщика взят из CodeWalker (`CodeWalker.Core/Resources/magic.dat`).

CodeWalker: Copyright (c) 2017-2019 dexyfex. Для этих частей в репозитории CodeWalker лицензия
отдельно не указана, поэтому условия MIT выше к ним не относятся.

## Инструменты сборки

Текстуры сжимаются утилитой `texconv` из [DirectXTex](https://github.com/microsoft/DirectXTex)
(Microsoft). В установщик она не входит.
