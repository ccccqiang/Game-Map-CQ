import cv2
import numpy as np
import mss
import tkinter as tk
from PIL import Image, ImageTk
import torch
import kornia as K
from kornia.feature import LoFTR
import ssl
import config
import os
import sys
import subprocess
import win32gui, win32ui, win32con, win32api

ssl._create_default_https_context = ssl._create_unverified_context


class ScreenGrabber:
    """屏幕/采集卡捕获器"""
    def __init__(self, use_capture_device=False, device_index=0):
        self.use_capture_device = use_capture_device
        self.device_index = device_index

        if self.use_capture_device:
            print(f"正在初始化采集卡 (设备索引: {device_index})...")
            self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                raise ValueError(f"无法打开采集卡设备 {self.device_index}")
            # 使用测试验证的最佳配置
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 60)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # 测试实际帧率
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"采集卡配置: {actual_width}x{actual_height} @ {actual_fps} FPS")
            print("采集卡初始化成功！")

    def grab_screen(self, region=None):
        if self.use_capture_device:
            # 从采集卡获取帧
            ret, frame = self.cap.read()
            if not ret:
                raise RuntimeError("从采集卡获取帧失败")

            # 使用配置文件中的 MINIMAP 坐标裁剪小地图区域
            if region:
                # 如果传入了 region 参数，使用它（兼容旧接口）
                left = region.get("left", 0)
                top = region.get("top", 0)
                width = region.get("width", 120)
                height = region.get("height", 120)
            else:
                # 否则使用 config 中的配置
                import config
                minimap_cfg = config.MINIMAP
                left = minimap_cfg.get("left", 0)
                top = minimap_cfg.get("top", 0)
                width = minimap_cfg.get("width", 120)
                height = minimap_cfg.get("height", 120)
            
            # 裁剪指定区域
            frame = frame[top:top+height, left:left+width]
            return frame

        else:
            # 使用 Windows API 进行屏幕捕获
            hwin = win32gui.GetDesktopWindow()
            if region:
                left, top, x2, y2 = region
                width = x2 - left
                height = y2 - top
            else:
                width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
                height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
                left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
                top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

            hwindc = win32gui.GetWindowDC(hwin)
            srcdc = win32ui.CreateDCFromHandle(hwindc)
            memdc = srcdc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(srcdc, width, height)
            memdc.SelectObject(bmp)
            memdc.BitBlt((0, 0), (width, height), srcdc, (left, top), win32con.SRCCOPY)
            signedIntsArray = bmp.GetBitmapBits(True)
            img = np.frombuffer(signedIntsArray, dtype='uint8')
            img.shape = (height, width, 4)

            srcdc.DeleteDC()
            memdc.DeleteDC()
            win32gui.ReleaseDC(hwin, hwindc)
            win32gui.DeleteObject(bmp.GetHandle())
            return img

    def release(self):
        """释放资源"""
        if self.use_capture_device:
            self.cap.release()


# ... 顶部的 import 区域 ...

def run_selector_if_needed(force=False):
    """
    检查是否需要运行小地图校准工具。
    :param force: 如果为 True，无视配置强制重新校准
    """
    # 检查 config.json 中是否已经有了合法的坐标
    minimap_cfg = config.settings.get("MINIMAP", {})
    has_valid_config = minimap_cfg and "top" in minimap_cfg and "left" in minimap_cfg

    if not has_valid_config or force:
        print("未检测到有效的小地图坐标，或请求重新校准。")
        print(">>> 正在启动小地图选择器...")

        # 兼容打包后的 .exe 运行路径
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
            selector_path = os.path.join(base_dir, "MinimapSetup.exe")  # 假设你把 selector 打包成了这个名字
            command = [selector_path]
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            selector_path = os.path.join(base_dir, "selector.py")
            command = [sys.executable, selector_path]

        try:
            # 阻塞运行：等待 selector 窗口关闭后，才会继续执行下面的代码
            subprocess.run(command, check=True)
            print("<<< 选择器关闭，坐标已更新！")

            # 重要：因为配置文件被 selector 修改了，我们需要重新加载一次 config 模块的数据
            import importlib
            importlib.reload(config)

        except FileNotFoundError:
            print(f"❌ 严重错误：找不到小地图选择器工具！期望路径：{selector_path}")
            print("请手动修改 config.json 或确保选择器工具存在。")
            sys.exit(1)  # 如果连选择器都没有，且没有配置，只能退出程序
        except subprocess.CalledProcessError:
            print("⚠️ 选择器异常退出，可能未保存坐标。")


# class AIMapTrackerApp:
#     def __init__(self, root):
# ...

class AIMapTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI 智能雷达跟点 (双图分离)")

        self.root.attributes("-topmost", True)
        # --- 使用配置文件中的悬浮窗几何设置 ---
        self.root.geometry(config.WINDOW_GEOMETRY)

        # --- 1. 加载 AI 模型 ---
        print("正在加载 LoFTR AI 模型...")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"当前计算设备: {self.device}")
        self.matcher = LoFTR(pretrained='outdoor').to(self.device)
        self.matcher.eval()
        print("AI 模型加载完成！")

        # --- 2. 加载【双地图】 ---
        print(f"正在加载逻辑大地图 ({config.LOGIC_MAP_PATH})...")
        self.logic_map_bgr = cv2.imread(config.LOGIC_MAP_PATH)
        if self.logic_map_bgr is None:
            raise FileNotFoundError(f"找不到逻辑地图: {config.LOGIC_MAP_PATH}！")
        self.map_height, self.map_width = self.logic_map_bgr.shape[:2]

        print(f"正在加载显示大地图 ({config.DISPLAY_MAP_PATH})...")
        self.display_map_bgr = cv2.imread(config.DISPLAY_MAP_PATH)
        if self.display_map_bgr is None:
            raise FileNotFoundError(f"找不到显示地图: {config.DISPLAY_MAP_PATH}！")

        # --- 3. 追踪状态机初始化 ---
        self.state = "GLOBAL_SCAN"  # 初始状态为全局雷达扫描
        self.last_x = 0
        self.last_y = 0

        # --- 使用配置文件中的雷达与追踪参数 ---
        self.scan_size = config.AI_SCAN_SIZE
        self.scan_step = config.AI_SCAN_STEP
        self.scan_x = 0
        self.scan_y = 0

        self.search_radius = config.AI_TRACK_RADIUS
        self.lost_frames = 0

        # 注意：AI 模式下彻底丢失几帧就切回雷达扫描。
        # 你可以考虑在 config 里单独加一个 AI_MAX_LOST_FRAMES = 3，或者直接在这里用一个较小的数字
        self.max_lost_frames = 3
        
        # 优化：帧计数器，隔帧处理降低负载
        self.frame_count = 0
        self.skip_frames = 3  # 0=每帧都处理，1=隔一帧处理
        
        # 性能监控
        self.fps_counter = 0
        self.fps_start_time = None
        self.current_fps = 0

        # --- 4. 截图与 UI ---
        # 根据配置选择使用采集卡还是屏幕截图
        if config.USE_CAPTURE_CARD:
            print("使用采集卡作为视频源")
            self.grabber = ScreenGrabber(use_capture_device=True, device_index=config.CAPTURE_DEVICE_INDEX)
        else:
            print("使用屏幕截图作为视频源")
            self.sct = mss.mss()
            self.grabber = None
        
        # --- 使用配置文件中的截图区域 ---
        self.minimap_region = config.MINIMAP

        # --- 使用配置文件中的视野大小 (VIEW_SIZE) ---
        self.canvas = tk.Canvas(root, width=config.VIEW_SIZE, height=config.VIEW_SIZE, bg='#2b2b2b')
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.image_on_canvas = None

        self.update_tracker()

    def preprocess_image(self, img_bgr):
        """优化：减少不必要的resize操作"""
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        h, w = img_gray.shape
        # 只在必要时resize到8的倍数
        new_h = h - (h % 8)
        new_w = w - (w % 8)
        if new_h != h or new_w != w:
            img_gray = cv2.resize(img_gray, (new_w, new_h))
        tensor = K.image_to_tensor(img_gray, False).float() / 255.0
        return tensor.to(self.device)

    def update_tracker(self):
        # 性能监控：计算 FPS
        import time
        if self.fps_start_time is None:
            self.fps_start_time = time.time()
        
        self.fps_counter += 1
        elapsed = time.time() - self.fps_start_time
        if elapsed >= 1.0:  # 每秒更新一次 FPS
            self.current_fps = self.fps_counter / elapsed
            self.fps_counter = 0
            self.fps_start_time = time.time()
        
        # 优化：跳帧机制，减少 AI 推理频率
        self.frame_count += 1
        should_process = (self.frame_count % (self.skip_frames + 1) == 0)
        
        # 1. 获取小地图（每帧都获取，保证实时性）
        if config.USE_CAPTURE_CARD and self.grabber:
            # 从采集卡获取图像（使用配置的区域）
            minimap_bgr = self.grabber.grab_screen(region=self.minimap_region)
        else:
            # 从屏幕截图获取图像
            screenshot = self.sct.grab(self.minimap_region)
            minimap_bgr = np.array(screenshot)[:, :, :3]

        found = False
        display_crop = None
        half_view = config.VIEW_SIZE // 2  # 视野的一半，用于计算裁剪范围

        # ==========================================
        # 状态机：确定当前的搜索区域
        # ==========================================
        if self.state == "GLOBAL_SCAN":
            x1 = self.scan_x
            y1 = self.scan_y
            x2 = min(self.map_width, x1 + self.scan_size)
            y2 = min(self.map_height, y1 + self.scan_size)

            display_crop = self.display_map_bgr[y1:y2, x1:x2].copy()
            display_crop = cv2.resize(display_crop, (config.VIEW_SIZE, int(config.VIEW_SIZE * (y2 - y1) / (x2 - x1))))

        else:  # TRACKING_LOCAL
            x1 = max(0, self.last_x - self.search_radius)
            y1 = max(0, self.last_y - self.search_radius)
            x2 = min(self.map_width, self.last_x + self.search_radius)
            y2 = min(self.map_height, self.last_y + self.search_radius)

        # 2. 只在需要处理的帧上运行 AI
        if should_process:
            # 从【逻辑地图】上截取搜索区域，喂给 AI
            local_logic_map = self.logic_map_bgr[y1:y2, x1:x2]

            if local_logic_map.shape[0] >= 16 and local_logic_map.shape[1] >= 16:
                tensor_mini = self.preprocess_image(minimap_bgr)
                tensor_big_local = self.preprocess_image(local_logic_map)

                input_dict = {"image0": tensor_mini, "image1": tensor_big_local}

                with torch.no_grad():
                    correspondences = self.matcher(input_dict)

                mkpts0 = correspondences['keypoints0'].cpu().numpy()
                mkpts1 = correspondences['keypoints1'].cpu().numpy()
                confidence = correspondences['confidence'].cpu().numpy()

                # --- 使用配置文件中的置信度阈值 ---
                valid_idx = confidence > config.AI_CONFIDENCE_THRESHOLD
                mkpts0 = mkpts0[valid_idx]
                mkpts1 = mkpts1[valid_idx]

                # ==========================================
                # AI 结果处理与状态切换
                # ==========================================
                # --- 使用配置文件中的最小匹配点数 ---
                if len(mkpts0) >= config.AI_MIN_MATCH_COUNT:
                    # --- 使用配置文件中的 RANSAC 误差阈值 ---
                    M, mask = cv2.findHomography(mkpts0, mkpts1, cv2.RANSAC, config.AI_RANSAC_THRESHOLD)

                    if M is not None:
                        h, w = minimap_bgr.shape[:2]
                        center_pt = np.float32([[[w / 2, h / 2]]])
                        dst_center_local = cv2.perspectiveTransform(center_pt, M)

                        center_x = int(dst_center_local[0][0][0] + x1)
                        center_y = int(dst_center_local[0][0][1] + y1)

                        if 0 <= center_x < self.map_width and 0 <= center_y < self.map_height:
                            found = True

                            self.last_x = center_x
                            self.last_y = center_y
                            self.state = "LOCAL_TRACK"
                            self.lost_frames = 0
                            
                            # 优化：追踪稳定后增加跳帧
                            if self.skip_frames < 2:
                                self.skip_frames += 1  # 最多隔2帧处理（3倍加速）

                            # 从【显示地图】截取周围的视野画出来 (使用 config.VIEW_SIZE)
                            vy1 = max(0, center_y - half_view)
                            vy2 = min(self.map_height, center_y + half_view)
                            vx1 = max(0, center_x - half_view)
                            vx2 = min(self.map_width, center_x + half_view)

                            display_crop = self.display_map_bgr[vy1:vy2, vx1:vx2].copy()

                            local_cx = center_x - vx1
                            local_cy = center_y - vy1
                            cv2.circle(display_crop, (local_cx, local_cy), radius=10, color=(0, 0, 255), thickness=-1)
                            cv2.circle(display_crop, (local_cx, local_cy), radius=12, color=(255, 255, 255), thickness=2)
        else:
            # 跳过的帧：如果正在追踪，保持显示上次位置
            if self.state == "LOCAL_TRACK" and self.lost_frames == 0:
                vy1 = max(0, self.last_y - half_view)
                vy2 = min(self.map_height, self.last_y + half_view)
                vx1 = max(0, self.last_x - half_view)
                vx2 = min(self.map_width, self.last_x + half_view)
                display_crop = self.display_map_bgr[vy1:vy2, vx1:vx2].copy()
                
                local_cx = self.last_x - vx1
                local_cy = self.last_y - vy1
                cv2.circle(display_crop, (local_cx, local_cy), radius=10, color=(0, 255, 0), thickness=-1)
                cv2.circle(display_crop, (local_cx, local_cy), radius=12, color=(255, 255, 255), thickness=2)

        # ==========================================
        # 丢失处理与雷达网格更新
        # ==========================================
        if not found:
            if self.state == "LOCAL_TRACK":
                self.lost_frames += 1
                if self.lost_frames <= self.max_lost_frames:
                    vy1 = max(0, self.last_y - half_view)
                    vy2 = min(self.map_height, self.last_y + half_view)
                    vx1 = max(0, self.last_x - half_view)
                    vx2 = min(self.map_width, self.last_x + half_view)
                    display_crop = self.display_map_bgr[vy1:vy2, vx1:vx2].copy()

                    local_cx = self.last_x - vx1
                    local_cy = self.last_y - vy1
                    cv2.circle(display_crop, (local_cx, local_cy), radius=10, color=(0, 255, 255), thickness=-1)
                else:
                    print("彻底丢失目标，启动全局雷达扫描...")
                    self.state = "GLOBAL_SCAN"
                    self.scan_x = 0
                    self.scan_y = 0
                    display_crop = np.zeros((config.VIEW_SIZE, config.VIEW_SIZE, 3), dtype=np.uint8)
                    cv2.putText(display_crop, "Radar Initializing...", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (0, 0, 255), 2)

            elif self.state == "GLOBAL_SCAN":
                self.scan_x += self.scan_step
                if self.scan_x >= self.map_width:
                    self.scan_x = 0
                    self.scan_y += self.scan_step
                    if self.scan_y >= self.map_height:
                        self.scan_x = 0
                        self.scan_y = 0

        # ==========================================
        # 统一渲染输出到 UI
        # ==========================================
        display_rgb = cv2.cvtColor(display_crop, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(display_rgb)

        final_img = Image.new('RGB', (config.VIEW_SIZE, config.VIEW_SIZE), (43, 43, 43))
        # 将画面居中粘贴
        final_img.paste(pil_image,
                        (max(0, half_view - pil_image.width // 2), max(0, half_view - pil_image.height // 2)))

        self.tk_image = ImageTk.PhotoImage(final_img)

        if self.image_on_canvas is None:
            self.image_on_canvas = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        else:
            self.canvas.itemconfig(self.image_on_canvas, image=self.tk_image)

        # --- 使用配置文件中的刷新频率 ---
        # 优化：追踪状态下大幅提高刷新率
        if self.state == "LOCAL_TRACK":
            refresh_rate = 10  # 追踪时 10ms (100 FPS UI更新)
        else:
            refresh_rate = config.AI_REFRESH_RATE
        self.root.after(refresh_rate, self.update_tracker)


if __name__ == "__main__":

    run_selector_if_needed(force=True)
    root = tk.Tk()
    app = AIMapTrackerApp(root)
    root.mainloop()