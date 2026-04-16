import cv2
import time

print("正在测试采集卡帧率...")
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("❌ 无法打开采集卡设备 0")
    exit()

# 设置参数
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 60)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

actual_fps = cap.get(cv2.CAP_PROP_FPS)
actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"采集卡配置: {actual_width}x{actual_height} @ {actual_fps} FPS (设定值)")
print("\n开始测试实际帧率，按 Q 退出...\n")

frame_count = 0
start_time = time.time()

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ 读取帧失败")
        break
    
    frame_count += 1
    elapsed = time.time() - start_time
    
    # 每秒显示一次 FPS
    if elapsed >= 1.0:
        current_fps = frame_count / elapsed
        print(f"实时帧率: {current_fps:.1f} FPS | 分辨率: {frame.shape[1]}x{frame.shape[0]}")
        frame_count = 0
        start_time = time.time()
    
    # 显示画面
    cv2.imshow('Capture Card Test', frame)
    
    # 按 Q 退出
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print(f"\n测试结束")
