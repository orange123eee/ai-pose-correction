import cv2
import mediapipe as mp
import numpy as np
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
from PIL import Image, ImageDraw, ImageFont

# ================= 1. 核心配置区 =================
TEACHER_VIDEO = 'teacher.mp4'
STUDENT_VIDEO = 'student.mp4'
OUTPUT_VIDEO = 'output_correction.mp4'

TARGET_HEIGHT = 600

# --- 判定条件优化参数 ---
# 归一化坐标系下的空间距离阈值 (可根据严格程度微调，0.1~0.15较为合适)
NORM_DIST_THRESHOLD = 0.12
# 视觉状态保持帧数：一旦报错，红线和箭头至少停留10帧，防止视觉闪烁
HOLD_FRAMES = 10
# 滑动窗口大小（帧数）：平滑曲线，消除骨骼提取的抖动噪点
SMOOTH_WINDOW = 5

mp_pose = mp.solutions.pose

# 提取特征用于DTW对齐的核心关节点 (排除脸部和手指等干扰项)
CORE_JOINTS = [
    mp_pose.PoseLandmark.LEFT_SHOULDER.value, mp_pose.PoseLandmark.RIGHT_SHOULDER.value,
    mp_pose.PoseLandmark.LEFT_ELBOW.value, mp_pose.PoseLandmark.RIGHT_ELBOW.value,
    mp_pose.PoseLandmark.LEFT_WRIST.value, mp_pose.PoseLandmark.RIGHT_WRIST.value,
    mp_pose.PoseLandmark.LEFT_HIP.value, mp_pose.PoseLandmark.RIGHT_HIP.value,
    mp_pose.PoseLandmark.LEFT_KNEE.value, mp_pose.PoseLandmark.RIGHT_KNEE.value,
    mp_pose.PoseLandmark.LEFT_ANKLE.value, mp_pose.PoseLandmark.RIGHT_ANKLE.value
]

# 用于绘制箭头纠错的具体关节点
CHECK_JOINTS = {
    mp_pose.PoseLandmark.LEFT_WRIST.value, mp_pose.PoseLandmark.RIGHT_WRIST.value,
    mp_pose.PoseLandmark.LEFT_ELBOW.value, mp_pose.PoseLandmark.RIGHT_ELBOW.value,
    mp_pose.PoseLandmark.LEFT_KNEE.value, mp_pose.PoseLandmark.RIGHT_KNEE.value,
    mp_pose.PoseLandmark.LEFT_ANKLE.value, mp_pose.PoseLandmark.RIGHT_ANKLE.value
}

# ================= 2. 算法引擎区 =================


def get_normalized_skeleton(landmarks):
    """空间归一化：将骨架转化为以骨盆为原点，根据躯干长度缩放的标准向量"""
    lms = np.array([(lm.x, lm.y, lm.z) for lm in landmarks])

    left_hip = lms[mp_pose.PoseLandmark.LEFT_HIP.value]
    right_hip = lms[mp_pose.PoseLandmark.RIGHT_HIP.value]
    root = (left_hip + right_hip) / 2.0

    left_shoulder = lms[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
    right_shoulder = lms[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
    shoulder_mid = (left_shoulder + right_shoulder) / 2.0
    torso_length = np.linalg.norm(shoulder_mid - root)

    if torso_length == 0:
        torso_length = 1.0

    normalized_lms = (lms - root) / torso_length
    return normalized_lms


def smooth_features(features, window_size):
    """滑动平均滤波"""
    if len(features) == 0:
        return features
    smoothed = np.copy(features)
    for i in range(features.shape[1]):
        smoothed[:, i] = np.convolve(features[:, i], np.ones(
            window_size)/window_size, mode='same')
    return smoothed


def extract_video_features(video_path):
    cap = cv2.VideoCapture(video_path)
    frames, raw_landmarks_list, norm_features_list = [], [], []

    ret, first_frame = cap.read()
    if not ret:
        return np.array([]), [], []

    orig_h, orig_w = first_frame.shape[:2]
    new_width = int(TARGET_HEIGHT * (orig_w / orig_h))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.resize(frame, (new_width, TARGET_HEIGHT))
            frames.append(frame)

            image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image.flags.writeable = False
            results = pose.process(image)

            if results.pose_landmarks:
                landmarks = results.pose_landmarks.landmark
                # 保存原始坐标用于画面渲染
                raw_landmarks_list.append([(lm.x, lm.y) for lm in landmarks])

                # 获取归一化骨架用于算法比对
                norm_lms = get_normalized_skeleton(landmarks)
                core_feature = np.array([norm_lms[idx]
                                        for idx in CORE_JOINTS]).flatten()
                norm_features_list.append(core_feature)
            else:
                raw_landmarks_list.append(
                    raw_landmarks_list[-1] if raw_landmarks_list else [(0, 0)]*33)
                norm_features_list.append(
                    norm_features_list[-1] if norm_features_list else [0.0]*(len(CORE_JOINTS)*3))

    cap.release()
    norm_features_list = smooth_features(
        np.array(norm_features_list), SMOOTH_WINDOW)
    return norm_features_list, frames, raw_landmarks_list

# ================= 3. 渲染辅助区 =================


def put_text_with_bg(img, text, position, text_color=(255, 255, 255), font_size=20):
    try:
        font = ImageFont.truetype("simhei.ttf", font_size, encoding="utf-8")
    except:
        font = ImageFont.load_default()

    img_pil = Image.fromarray(cv2.cvtColor(
        img, cv2.COLOR_BGR2RGB)).convert('RGBA')
    overlay = Image.new('RGBA', img_pil.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    left, top, right, bottom = draw.textbbox(position, text, font=font)
    pad = 8
    draw.rectangle([left-pad, top-pad, right+pad,
                   bottom+pad], fill=(0, 0, 0, 150))
    draw.text(position, text, font=font, fill=(
        text_color[0], text_color[1], text_color[2], 255))

    img_pil = Image.alpha_composite(img_pil, overlay).convert('RGB')
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def draw_skeleton(frame, landmarks, w, h, color, thickness=3):
    for connection in mp_pose.POSE_CONNECTIONS:
        p1, p2 = connection[0], connection[1]
        pt1 = (int(landmarks[p1][0] * w), int(landmarks[p1][1] * h))
        pt2 = (int(landmarks[p2][0] * w), int(landmarks[p2][1] * h))
        cv2.line(frame, pt1, pt2, color, thickness)
        cv2.circle(frame, pt1, thickness, color, -1)
        cv2.circle(frame, pt2, thickness, color, -1)

# ================= 4. 主流程 =================


def main():
    print("1. 提取特征中...")
    t_features, t_frames, t_raw_lms = extract_video_features(TEACHER_VIDEO)
    s_features, s_frames, s_raw_lms = extract_video_features(STUDENT_VIDEO)

    if len(t_features) == 0 or len(s_features) == 0:
        print("错误：无法读取视频。")
        return

    print("2. DTW 序列对齐中...")
    distance, path = fastdtw(s_features, t_features, dist=euclidean)
    print(f"对齐完成！共 {len(path)} 帧。")

    t_h, t_w, _ = t_frames[0].shape
    s_h, s_w, _ = s_frames[0].shape
    out = cv2.VideoWriter(OUTPUT_VIDEO, cv2.VideoWriter_fourcc(
        *'mp4v'), 30, (t_w + s_w, TARGET_HEIGHT))

    # 简化的状态机：只记录剩余报错帧数，用于防抖动
    ui_states = {joint_idx: 0 for joint_idx in CHECK_JOINTS}

    print("3. 生成视觉纠错视频...")

    last_idx = -1
    for student_idx, teacher_idx in path:
        t_frame, s_frame = t_frames[teacher_idx].copy(
        ), s_frames[student_idx].copy()
        t_raw, s_raw = t_raw_lms[teacher_idx], s_raw_lms[student_idx]

        # 核心比对
        t_feat = t_features[teacher_idx].reshape(-1, 3)
        s_feat = s_features[student_idx].reshape(-1, 3)

        active_error_joints = set()
        for i, joint_idx in enumerate(CORE_JOINTS):
            if joint_idx not in CHECK_JOINTS:
                continue

            # 计算归一化空间下的误差
            dist = euclidean(t_feat[i], s_feat[i])

            if dist > NORM_DIST_THRESHOLD:
                ui_states[joint_idx] = HOLD_FRAMES
            else:
                if ui_states[joint_idx] > 0:
                    ui_states[joint_idx] -= 1

            if ui_states[joint_idx] > 0:
                active_error_joints.add(joint_idx)

        # ---------------- 视觉渲染引擎 ----------------

        # 1. 绘制左侧标准演示
        draw_skeleton(t_frame, t_raw, t_w, t_h, (0, 255, 0), 3)

        # --- 新增：空间对齐算法 (将老师的骨架“附体”到学生身上) ---
        left_hip = mp_pose.PoseLandmark.LEFT_HIP.value
        right_hip = mp_pose.PoseLandmark.RIGHT_HIP.value
        left_shoulder = mp_pose.PoseLandmark.LEFT_SHOULDER.value
        right_shoulder = mp_pose.PoseLandmark.RIGHT_SHOULDER.value

        # 计算学生的 Root (中心点) 和躯干像素长度
        s_root_x = (s_raw[left_hip][0] + s_raw[right_hip][0]) / 2.0 * s_w
        s_root_y = (s_raw[left_hip][1] + s_raw[right_hip][1]) / 2.0 * s_h
        s_shoulder_x = (s_raw[left_shoulder][0] +
                        s_raw[right_shoulder][0]) / 2.0 * s_w
        s_shoulder_y = (s_raw[left_shoulder][1] +
                        s_raw[right_shoulder][1]) / 2.0 * s_h
        s_torso = np.hypot(s_shoulder_x - s_root_x, s_shoulder_y - s_root_y)

        # 计算老师的 Root 和躯干像素长度 (基于学生画面尺寸)
        t_root_x = (t_raw[left_hip][0] + t_raw[right_hip][0]) / 2.0 * s_w
        t_root_y = (t_raw[left_hip][1] + t_raw[right_hip][1]) / 2.0 * s_h
        t_shoulder_x = (t_raw[left_shoulder][0] +
                        t_raw[right_shoulder][0]) / 2.0 * s_w
        t_shoulder_y = (t_raw[left_shoulder][1] +
                        t_raw[right_shoulder][1]) / 2.0 * s_h
        t_torso = np.hypot(t_shoulder_x - t_root_x, t_shoulder_y - t_root_y)

        # 计算缩放比例，防止除以0
        scale = s_torso / t_torso if t_torso > 0 else 1.0

        # 生成对齐后的老师骨架坐标 (Aligned Ghost)
        aligned_t_pts = {}
        for idx in range(33):  # MediaPipe共有33个点
            tx = t_raw[idx][0] * s_w
            ty = t_raw[idx][1] * s_h
            # 平移到原点 -> 缩放以匹配身高 -> 平移到学生位置
            ax = s_root_x + (tx - t_root_x) * scale
            ay = s_root_y + (ty - t_root_y) * scale
            aligned_t_pts[idx] = (int(ax), int(ay))
        # --------------------------------------------------------

        # 2. 制作右侧画面的半透明“残影” (Teacher Ghosting)
        overlay = s_frame.copy()
        for connection in mp_pose.POSE_CONNECTIONS:
            p1, p2 = connection[0], connection[1]
            # 使用对齐后的坐标绘制残影！
            cv2.line(overlay, aligned_t_pts[p1],
                     aligned_t_pts[p2], (100, 255, 100), 3)
        cv2.addWeighted(overlay, 0.4, s_frame, 0.6, 0, s_frame)

        # 3. 绘制学生实际骨架
        for connection in mp_pose.POSE_CONNECTIONS:
            p1, p2 = connection[0], connection[1]
            pt1_s = (int(s_raw[p1][0] * s_w), int(s_raw[p1][1] * s_h))
            pt2_s = (int(s_raw[p2][0] * s_w), int(s_raw[p2][1] * s_h))

            is_error_line = (p1 in active_error_joints) or (
                p2 in active_error_joints)

            if is_error_line:
                cv2.line(s_frame, pt1_s, pt2_s, (0, 0, 255), 5)  # 错误：红色粗线
            else:
                cv2.line(s_frame, pt1_s, pt2_s, (255, 180, 0), 3)  # 正常：蓝/橙色线

        # 4. 绘制动态牵引箭头
        for joint_idx in active_error_joints:
            wrong_pt = (int(s_raw[joint_idx][0] * s_w),
                        int(s_raw[joint_idx][1] * s_h))
            # 箭头目标点改为对齐后的坐标！
            target_pt = aligned_t_pts[joint_idx]

            # 限制箭头长度，防止微小误差引发巨大箭头 (视觉优化)
            dist_px = np.hypot(
                target_pt[0] - wrong_pt[0], target_pt[1] - wrong_pt[1])
            if dist_px > 15:  # 只有相差15像素以上才画箭头，避免原地鬼畜
                cv2.arrowedLine(s_frame, wrong_pt, target_pt,
                                (0, 0, 255), 3, tipLength=0.2)

        # ---------------- UI 与 拼接 ----------------

        combined_frame = np.hstack((t_frame, s_frame))

        # 极简 UI
        combined_frame = put_text_with_bg(
            combined_frame, "标准演示", (15, 15), (0, 255, 0), 28)

        out.write(combined_frame)

        if student_idx % 30 == 0 and student_idx != last_idx:
            print(f"进度: {student_idx} 帧...")
            last_idx = student_idx

    out.release()
    print(f"4. 完毕！请查看 {OUTPUT_VIDEO}")


if __name__ == '__main__':
    main()
