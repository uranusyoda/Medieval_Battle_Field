# CMU 行走与跑步动作来源

来自 Carnegie Mellon University Graphics Lab Motion Capture Database，同一演员 Subject 35，采样率 120 Hz。

| 文件 | 上游说明 | 原始下载 |
| --- | --- | --- |
| `35.asf` | Subject 35 校准骨架 | https://mocap.cs.cmu.edu/subjects/35/35.asf |
| `35_01.amc` | walk | https://mocap.cs.cmu.edu/subjects/35/35_01.amc |
| `35_18.amc` | run/jog | https://mocap.cs.cmu.edu/subjects/35/35_18.amc |

动作目录：https://mocap.cs.cmu.edu/search.php?subjectnumber=35

上游许可及使用说明：https://mocap.cs.cmu.edu/ 和 https://mocap.cs.cmu.edu/faqs.php 。上游允许免费用于商业与非商业成品，可以复制、修改及分发；不允许将动作数据本身直接转售（包括转换格式）。本项目将这些动作重定向为角色动画。

建议的来源致谢：The data used in this project was obtained from mocap.cs.cmu.edu. The database was created with funding from NSF EIA-0196217.

上游特别提醒手腕和脚趾可能有噪声；finger/thumb 通道并非真实捕捉，重定向时不采用，角色手型另行制作。

长度按官方 FAQ 乘以 `(1 / 0.45) * 2.54 / 100` 转换为米。`tools/cmu_motion.py` 读取原始 ASF/AMC 并输出 Blender 坐标：+Z 向上、-Y 向前。
