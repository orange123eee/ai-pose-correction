# AI 动作姿态纠错系统

输入一段老师示范视频和一段学生练习视频，自动输出左右对比的纠错视频。

## 效果

- **左半屏**：老师视频 + 绿色骨架（标准参考）
- **右半屏**：学生视频 + 三层叠加渲染
  - 半透明老师残影（正确位置参考）
  - 橙色/红色骨架（正确/错误部位）
  - 红色箭头（指向正确方向）

## 使用

```bash
pip install -r requirements.txt
```

将 `teacher.mp4` 和 `student.mp4` 放在项目目录，然后：

```bash
python new_ap.py
```

输出 `output_correction.mp4`。

## 参数调节

编辑 `new_ap.py` 顶部配置区：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `NORM_DIST_THRESHOLD` | 0.12 | 误差判定阈值（躯干长度的 12%） |
| `HOLD_FRAMES` | 10 | 错误标注保持帧数 |
| `SMOOTH_WINDOW` | 5 | 滑动平均窗口大小 |

## 技术栈

- MediaPipe — 人体姿态估计（33 个 3D 关键点）
- OpenCV — 视频处理与渲染
- fastdtw — 动态时间规整序列对齐
- NumPy / SciPy — 数值计算
- Pillow — 中文字体渲染
