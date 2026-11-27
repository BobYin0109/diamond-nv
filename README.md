# Diamond NV 共焦扫描分析工具

批量处理 Diamond-II 导出的 XY 共焦荧光扫描数据。C++ 核心重建二维荧光计数图，执行平滑、局部背景扣除和对比度计算，再按局部波动对候选峰排序。Python 负责 Excel 导入、批量运行和预览图。

从仪器、装样、采集、复测到算法与验证的细节见 [实验与数据处理全流程](WORKFLOW.md)。仓库附带合成示例生成器，以及经过整理的 `Samples/CS` 和 `Samples/CW` 实测表。

## Windows 运行包

解压后在包目录打开 PowerShell，运行内置的合成示例。

```powershell
.\DiamondNV.exe .\demo_scan.xlsx --out .\demo_output --top 3
```

把输入路径替换为一个 Excel 文件或包含扫描文件的目录，即可处理自己的数据。输出目录需为新目录。输入为含 `data` 工作表的 `.xlsx`，前四列依次是 `X (μm)`、`Y (μm)`、`Z (μm)` 和 `Count(kcps)`。扫描需覆盖一张完整的固定 Z 平面。

## 从源码运行

已验证 Windows x64、Python 3.13 和 Zig 0.15.2。在源码目录运行以下命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\build.ps1
.\.venv\Scripts\python.exe .\test_candidate_detection.py
.\.venv\Scripts\python.exe .\examples\make_demo.py .\demo_scan.xlsx
.\.venv\Scripts\python.exe .\analyze_scans.py .\demo_scan.xlsx --out .\demo_output --top 3
```

若 Zig 不在 PATH，可向 `build.ps1` 传入 `-Zig` 和完整的 `zig.exe` 路径。构建 Windows 运行包时，在全新的源码目录使用 `requirements-build.txt` 安装依赖，再将构建命令改为 `.\build.ps1 -Python .\.venv\Scripts\python.exe -Bundle`。生成目录为 `dist/DiamondNV`。

## 输出

每份扫描生成一个子目录。

- `preview.png` 包含原图、增强图和候选点标注。两幅图各用自己的颜色刻度。
- `candidates.csv` 保存候选点排名、物理坐标（μm）、局部对比度和评分。
- `enhanced.csv` 保存逐像素原始计数、平滑值、背景估计、对比度和评分。
- 根目录的 `summary.json` 记录处理的扫描和候选点数量。

`--top` 控制预览中标注多少个候选点。可用 `--cw` 对照同日期、同扫描名称下的历史连续波复测位置。匹配阈值为归一化距离两步以内，覆盖率用于对照历史选点。程序输出的是候选峰，NV 色心身份需根据独立实验验证。

运行包内的工作簿为合成数据，三个设计峰的 XY 坐标是 (2.8, 3.2)、(8.4, 4.8) 和 (6.0, 9.2) μm。
