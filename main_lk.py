import cv2
import numpy as np
import mss
import tkinter as tk
from tkinter import ttk
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
import json
import glob
import threading
import queue
import time

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
            self.cap.set(cv2.CAP_PROP_FPS, 240)
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
        
        # --- 惯性导航参数 ---
        self.inertial_x = None  # 惯性预测坐标（None表示未初始化）
        self.inertial_y = None
        self.velocity_x = 0  # 速度估计
        self.velocity_y = 0
        self.last_update_time = time.time()  # 上次AI更新时间

        # --- 使用配置文件中的雷达与追踪参数 ---
        self.scan_size = config.AI_SCAN_SIZE
        self.scan_step = config.AI_SCAN_STEP
        self.scan_x = 0
        self.scan_y = 0
        
        # --- 首次定位优化：缩小初始扫描范围 ---
        self.initial_scan_done = False  # 标记是否完成首次定位

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
        
        # --- 路径规划系统初始化 ---
        self.routes_dir = "routes"  # 路线文件目录
        self.available_routes = self.load_available_routes()
        self.current_route = None
        self.current_route_index = 0
        self.route_planning_enabled = False
        self.collected_points = set()  # 已采集的点ID集合
        self.picking_radius = 30  # 采集半径（像素）
        
        # --- 多线程支持 ---
        self.is_running = True
        self.frame_queue = queue.Queue(maxsize=2)  # 帧队列
        self.result_queue = queue.Queue(maxsize=1)  # 结果队列
        self.ai_thread = None
        self.last_ai_result = None  # 缓存最新的AI结果

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

        # --- 添加路线控制UI ---
        self.create_route_control_ui()

        # --- 启动AI推理线程 ---
        self.ai_thread = threading.Thread(target=self.ai_inference_loop, daemon=True)
        self.ai_thread.start()
        print("✅ AI推理线程已启动")

        self.update_tracker()

    def ai_inference_loop(self):
        """AI推理线程：独立运行LoFTR匹配（优化版）"""
        print("🧠 AI推理线程运行中...")
        
        while self.is_running:
            try:
                # 从队列获取待处理的帧
                try:
                    frame_data = self.frame_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                minimap_bgr, search_region = frame_data
                x1, y1, x2, y2 = search_region
                
                # 从逻辑地图截取搜索区域
                local_logic_map = self.logic_map_bgr[y1:y2, x1:x2]
                
                if local_logic_map.shape[0] < 16 or local_logic_map.shape[1] < 16:
                    continue
                
                # 优化1：动态调整图像分辨率（追踪时用小图，扫描时用大图）
                h, w = local_logic_map.shape[:2]
                if self.state == "LOCAL_TRACK" and max(h, w) > 400:
                    # 追踪状态：缩小到400px以内，提速3倍
                    scale = 400 / max(h, w)
                    local_logic_map = cv2.resize(local_logic_map, (int(w*scale), int(h*scale)))
                    scale_factor = 1.0 / scale  # 记录缩放比例用于还原坐标
                else:
                    scale_factor = 1.0
                
                # 预处理图像
                tensor_mini = self.preprocess_image(minimap_bgr)
                tensor_big_local = self.preprocess_image(local_logic_map)
                
                input_dict = {"image0": tensor_mini, "image1": tensor_big_local}
                
                # AI推理
                with torch.no_grad():
                    correspondences = self.matcher(input_dict)
                
                mkpts0 = correspondences['keypoints0'].cpu().numpy()
                mkpts1 = correspondences['keypoints1'].cpu().numpy()
                confidence = correspondences['confidence'].cpu().numpy()
                
                # 优化2：自适应置信度阈值（首次定位宽松，追踪严格）
                if not self.initial_scan_done:
                    conf_threshold = 0.2  # 首次定位：极低阈值
                    min_matches = 3       # 最少3个点
                elif self.state == "LOCAL_TRACK":
                    conf_threshold = 0.4  # 追踪：中等阈值
                    min_matches = 5       # 需要5个点保证精度
                else:
                    conf_threshold = config.AI_CONFIDENCE_THRESHOLD
                    min_matches = config.AI_MIN_MATCH_COUNT
                
                # 过滤低置信度匹配点
                valid_idx = confidence > conf_threshold
                mkpts0 = mkpts0[valid_idx]
                mkpts1 = mkpts1[valid_idx]
                
                # 计算变换矩阵
                result = None
                if len(mkpts0) >= min_matches:
                    # 优化3：根据状态调整RANSAC参数
                    ransac_thresh = 3.0 if self.state == "LOCAL_TRACK" else config.AI_RANSAC_THRESHOLD
                    M, mask = cv2.findHomography(mkpts0, mkpts1, cv2.RANSAC, ransac_thresh)
                    
                    if M is not None:
                        h, w = minimap_bgr.shape[:2]
                        center_pt = np.float32([[[w / 2, h / 2]]])
                        dst_center_local = cv2.perspectiveTransform(center_pt, M)
                        
                        center_x = int(dst_center_local[0][0][0] * scale_factor + x1)
                        center_y = int(dst_center_local[0][0][1] * scale_factor + y1)
                        
                        if 0 <= center_x < self.map_width and 0 <= center_y < self.map_height:
                            result = {
                                'found': True,
                                'center_x': center_x,
                                'center_y': center_y,
                                'match_count': len(mkpts0)
                            }
                
                if result is None:
                    result = {'found': False}
                
                # 将结果放入结果队列（非阻塞）
                try:
                    if self.result_queue.full():
                        self.result_queue.get_nowait()
                    self.result_queue.put_nowait(result)
                except queue.Full:
                    pass
                
            except Exception as e:
                print(f"❌ AI推理线程错误: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
    
    def load_available_routes(self):
        """加载所有可用的路线文件"""
        routes = {}
        if not os.path.exists(self.routes_dir):
            print(f"警告: 路线目录 {self.routes_dir} 不存在")
            return routes
        
        route_files = glob.glob(os.path.join(self.routes_dir, "*.json"))
        for file_path in route_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    route_data = json.load(f)
                    route_name = os.path.splitext(os.path.basename(file_path))[0]
                    routes[route_name] = {
                        'file': file_path,
                        'data': route_data,
                        'points': route_data.get('points', [])
                    }
            except Exception as e:
                print(f"加载路线文件失败 {file_path}: {e}")
        
        print(f"已加载 {len(routes)} 条路线")
        return routes
    
    def select_route(self, route_name):
        """选择要执行的路线"""
        if route_name in self.available_routes:
            self.current_route = self.available_routes[route_name]
            self.current_route_index = 0
            self.collected_points.clear()
            print(f"已选择路线: {route_name}, 共 {len(self.current_route['points'])} 个节点")
            return True
        return False
    
    def get_next_waypoint(self):
        """获取下一个未完成的航点"""
        if not self.current_route or self.current_route_index >= len(self.current_route['points']):
            return None
        return self.current_route['points'][self.current_route_index]
    
    def check_waypoint_reached(self, current_x, current_y, waypoint):
        """检查是否到达航点（基于距离判断）"""
        radius = waypoint.get('radius', self.picking_radius)
        dist = np.sqrt((current_x - waypoint['x'])**2 + (current_y - waypoint['y'])**2)
        return dist <= radius
    
    def advance_to_next_waypoint(self):
        """前进到下一个航点"""
        if self.current_route and self.current_route_index < len(self.current_route['points']):
            point_id = f"{self.current_route_index}_{self.current_route['points'][self.current_route_index]['x']}_{self.current_route['points'][self.current_route_index]['y']}"
            self.collected_points.add(point_id)
            self.current_route_index += 1
            
            # 检查是否完成整条路线
            if self.current_route_index >= len(self.current_route['points']):
                if self.current_route['data'].get('loop', False):
                    print("路线循环，重新开始")
                    self.current_route_index = 0
                    self.collected_points.clear()
                else:
                    print("路线已完成！")
                    return False
            return True
        return False
    
    def calculate_nearest_route(self, current_x, current_y, num_points=5):
        """计算从当前位置开始的最近路线（贪心算法）"""
        if not self.current_route:
            return []
        
        remaining_points = [
            p for i, p in enumerate(self.current_route['points'])
            if i >= self.current_route_index
        ]
        
        if not remaining_points:
            return []
        
        route = []
        curr_x, curr_y = current_x, current_y
        candidates = remaining_points.copy()
        
        # 贪心算法：每次找最近的点
        for _ in range(min(num_points, len(candidates))):
            nearest = None
            min_dist_sq = float('inf')
            
            for p in candidates:
                dist_sq = (p['x'] - curr_x)**2 + (p['y'] - curr_y)**2
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    nearest = p
            
            if nearest:
                route.append(nearest)
                candidates.remove(nearest)
                curr_x, curr_y = nearest['x'], nearest['y']
        
        return route

    def create_route_control_ui(self):
        """创建路线控制UI组件"""
        control_frame = tk.Frame(self.root, bg='#2b2b2b')
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # 路线选择下拉框
        route_names = list(self.available_routes.keys()) if self.available_routes else ["无可用路线"]
        self.route_var = tk.StringVar(value=route_names[0] if route_names else "")
        self.route_combo = ttk.Combobox(
            control_frame,
            textvariable=self.route_var,
            values=route_names,
            state="readonly",
            width=20
        )
        self.route_combo.pack(side=tk.LEFT, padx=5)
        
        # 加载路线按钮
        load_btn = tk.Button(
            control_frame,
            text="加载路线",
            command=self.on_load_route,
            bg='#3c3f41',
            fg='white',
            activebackground='#4b4e50',
            relief=tk.FLAT,
            padx=10
        )
        load_btn.pack(side=tk.LEFT, padx=2)
        
        # 开启/关闭路线规划
        self.route_planning_var = tk.BooleanVar(value=False)
        planning_cb = tk.Checkbutton(
            control_frame,
            text="启用路线导航",
            variable=self.route_planning_var,
            bg='#2b2b2b',
            fg='white',
            selectcolor='#3c3f41',
            activebackground='#2b2b2b',
            activeforeground='white',
            command=self.on_toggle_route_planning
        )
        planning_cb.pack(side=tk.LEFT, padx=5)
        
        # 重置路线按钮
        reset_btn = tk.Button(
            control_frame,
            text="重置路线",
            command=self.on_reset_route,
            bg='#4a2b2b',
            fg='white',
            activebackground='#6e3a3a',
            relief=tk.FLAT,
            padx=10
        )
        reset_btn.pack(side=tk.LEFT, padx=2)
        
        # 路线状态标签
        self.route_status_label = tk.Label(
            control_frame,
            text="未加载路线",
            fg='yellow',
            bg='#2b2b2b',
            anchor='w'
        )
        self.route_status_label.pack(side=tk.RIGHT, padx=5)
    
    def on_load_route(self):
        """加载选中的路线"""
        route_name = self.route_var.get()
        if self.select_route(route_name):
            self.route_planning_enabled = True
            self.route_planning_var.set(True)
            self.update_route_status()
    
    def on_toggle_route_planning(self):
        """切换路线规划开关"""
        self.route_planning_enabled = self.route_planning_var.get()
        if self.route_planning_enabled and not self.current_route:
            # 如果开启了但没有加载路线，自动加载第一个
            if self.available_routes:
                first_route = list(self.available_routes.keys())[0]
                self.select_route(first_route)
                self.route_var.set(first_route)
        self.update_route_status()
    
    def on_reset_route(self):
        """重置当前路线"""
        if self.current_route:
            self.current_route_index = 0
            self.collected_points.clear()
            print("路线已重置")
            self.update_route_status()
    
    def update_route_status(self):
        """更新路线状态显示"""
        if self.current_route:
            total = len(self.current_route['points'])
            current = self.current_route_index + 1 if self.current_route_index < total else total
            status = f"路线: {self.current_route_index + 1}/{total}"
            self.route_status_label.config(text=status, fg='cyan')
        else:
            self.route_status_label.config(text="未加载路线", fg='yellow')

    def preprocess_image(self, img_bgr):
        """预处理图像"""
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        h, w = img_gray.shape
        new_h = h - (h % 8)
        new_w = w - (w % 8)
        if new_h != h or new_w != w:
            img_gray = cv2.resize(img_gray, (new_w, new_h))
        tensor = K.image_to_tensor(img_gray, False).float() / 255.0
        return tensor.to(self.device)

    def update_tracker(self):
        # 性能监控：计算 FPS
        if self.fps_start_time is None:
            self.fps_start_time = time.time()
        
        self.fps_counter += 1
        elapsed = time.time() - self.fps_start_time
        if elapsed >= 1.0:  # 每秒更新一次 FPS
            self.current_fps = self.fps_counter / elapsed
            self.fps_counter = 0
            self.fps_start_time = time.time()
        
        # 1. 获取小地图（每帧都获取，保证实时性）
        if config.USE_CAPTURE_CARD and self.grabber:
            minimap_bgr = self.grabber.grab_screen(region=self.minimap_region)
        else:
            screenshot = self.sct.grab(self.minimap_region)
            minimap_bgr = np.array(screenshot)[:, :, :3]

        found = False
        display_crop = None
        half_view = config.VIEW_SIZE // 2

        # ==========================================
        # 状态机：确定当前的搜索区域
        # ==========================================
        if self.state == "GLOBAL_SCAN":
            # 首次定位：使用更大的扫描块提高匹配成功率
            if not self.initial_scan_done:
                scan_size = min(self.scan_size, 1200)  # 首次用1200x1200（原800太小）
                scan_step = min(self.scan_step, 800)   # 步长800（平衡速度与覆盖）
            else:
                scan_size = self.scan_size
                scan_step = self.scan_step
            
            x1 = self.scan_x
            y1 = self.scan_y
            x2 = min(self.map_width, x1 + scan_size)
            y2 = min(self.map_height, y1 + scan_size)

            display_crop = self.display_map_bgr[y1:y2, x1:x2].copy()
            display_crop = cv2.resize(display_crop, (config.VIEW_SIZE, int(config.VIEW_SIZE * (y2 - y1) / (x2 - x1))))

        else:  # TRACKING_LOCAL
            x1 = max(0, self.last_x - self.search_radius)
            y1 = max(0, self.last_y - self.search_radius)
            x2 = min(self.map_width, self.last_x + self.search_radius)
            y2 = min(self.map_height, self.last_y + self.search_radius)
        
        # 2. 将帧数据发送到AI线程（非阻塞）
        try:
            if self.frame_queue.full():
                self.frame_queue.get_nowait()
            self.frame_queue.put_nowait((minimap_bgr, (x1, y1, x2, y2)))
        except queue.Full:
            pass
        
        # 3. 检查AI推理结果（非阻塞）
        try:
            ai_result = self.result_queue.get_nowait()
            self.last_ai_result = ai_result
        except queue.Empty:
            ai_result = self.last_ai_result
        
        # 4. 处理AI结果
        if ai_result and ai_result.get('found', False):
            found = True
            center_x = ai_result['center_x']
            center_y = ai_result['center_y']
            
            # 标记首次定位完成
            if not self.initial_scan_done:
                self.initial_scan_done = True
                print(f"✅ 首次定位成功！坐标: ({center_x}, {center_y})")
            
            # 计算速度（用于惯性导航）
            current_time = time.time()
            dt = current_time - self.last_update_time
            if dt > 0 and dt < 1.0 and self.inertial_x is not None:
                self.velocity_x = (center_x - self.last_x) / dt
                self.velocity_y = (center_y - self.last_y) / dt
            
            self.last_x = center_x
            self.last_y = center_y
            self.inertial_x = center_x
            self.inertial_y = center_y
            self.last_update_time = current_time
            
            self.state = "LOCAL_TRACK"
            self.lost_frames = 0
            
            # 优化：追踪稳定后增加跳帧
            if self.skip_frames < 2:
                self.skip_frames += 1
            
            # --- 检查是否到达航点 ---
            if self.route_planning_enabled and self.current_route:
                self.check_and_advance_waypoint(center_x, center_y)
            
            # 从显示地图截取视野
            vy1 = max(0, center_y - half_view)
            vy2 = min(self.map_height, center_y + half_view)
            vx1 = max(0, center_x - half_view)
            vx2 = min(self.map_width, center_x + half_view)
            
            display_crop = self.display_map_bgr[vy1:vy2, vx1:vx2].copy()
            
            local_cx = center_x - vx1
            local_cy = center_y - vy1
            cv2.circle(display_crop, (local_cx, local_cy), radius=10, color=(0, 0, 255), thickness=-1)
            cv2.circle(display_crop, (local_cx, local_cy), radius=12, color=(255, 255, 255), thickness=2)
            
            # --- 绘制路线规划 ---
            if self.route_planning_enabled and self.current_route:
                self.draw_route_on_display(display_crop, vx1, vy1, center_x, center_y)
        else:
            # === 惯性导航：没有AI结果时使用预测位置 ===
            if self.state == "LOCAL_TRACK":
                current_time = time.time()
                dt = current_time - self.last_update_time
                
                # 如果超过500ms没有AI更新，才认为是真正丢失
                if dt < 0.5 and self.inertial_x is not None:
                    # 使用惯性预测位置
                    predicted_x = self.inertial_x + self.velocity_x * dt
                    predicted_y = self.inertial_y + self.velocity_y * dt
                    
                    # 边界限制
                    predicted_x = max(0, min(predicted_x, self.map_width - 1))
                    predicted_y = max(0, min(predicted_y, self.map_height - 1))
                    
                    # 不增加lost_frames，继续使用预测位置渲染
                    vy1 = max(0, int(predicted_y) - half_view)
                    vy2 = min(self.map_height, int(predicted_y) + half_view)
                    vx1 = max(0, int(predicted_x) - half_view)
                    vx2 = min(self.map_width, int(predicted_x) + half_view)
                    display_crop = self.display_map_bgr[vy1:vy2, vx1:vx2].copy()
                    
                    local_cx = int(predicted_x) - vx1
                    local_cy = int(predicted_y) - vy1
                    
                    # 黄色圆圈表示预测位置
                    cv2.circle(display_crop, (local_cx, local_cy), radius=10, color=(0, 255, 255), thickness=-1)
                    cv2.circle(display_crop, (local_cx, local_cy), radius=12, color=(255, 255, 255), thickness=2)
                    
                    # 绘制路线（使用预测位置）
                    if self.route_planning_enabled and self.current_route:
                        self.draw_route_on_display(display_crop, vx1, vy1, int(predicted_x), int(predicted_y))
                else:
                    # 真正丢失：超过500ms没有AI结果或惯性未初始化
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
                        self.inertial_x = None
                        self.inertial_y = None
                        display_crop = np.zeros((config.VIEW_SIZE, config.VIEW_SIZE, 3), dtype=np.uint8)
                        cv2.putText(display_crop, "Radar Initializing...", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                    (0, 0, 255), 2)

        # ==========================================
        # 丢失处理与雷达网格更新（仅在全局扫描时执行）
        # ==========================================
        if not found and self.state == "GLOBAL_SCAN":
            # 根据是否首次定位选择步长
            if not self.initial_scan_done:
                scan_step = min(self.scan_step, 800)
            else:
                scan_step = self.scan_step
            
            self.scan_x += scan_step
            if self.scan_x >= self.map_width:
                self.scan_x = 0
                self.scan_y += scan_step
                if self.scan_y >= self.map_height:
                    # 全图扫描完成，重置并继续
                    self.scan_x = 0
                    self.scan_y = 0
                    if not self.initial_scan_done:
                        print("⚠️  全图扫描未找到，继续循环扫描...")

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
        if self.state == "LOCAL_TRACK":
            refresh_rate = 10  # 追踪时 50ms (20 FPS UI更新，给AI更多时间)
        else:
            refresh_rate = config.AI_REFRESH_RATE
        self.root.after(refresh_rate, self.update_tracker)
    
    def on_closing(self):
        """窗口关闭时的清理工作"""
        print("\n🛑 正在关闭程序...")
        self.is_running = False
        
        # 等待AI线程结束
        if self.ai_thread and self.ai_thread.is_alive():
            print("⏳ 等待AI线程退出...")
            self.ai_thread.join(timeout=2.0)
        
        # 释放资源
        if self.grabber:
            self.grabber.release()
        
        print("✅ 程序已安全退出")
        self.root.destroy()
    
    def check_and_advance_waypoint(self, current_x, current_y):
        """检查当前坐标是否到达航点，如果是则前进到下一个"""
        next_wp = self.get_next_waypoint()
        if next_wp and self.check_waypoint_reached(current_x, current_y, next_wp):
            label = next_wp.get('label', f'节点 {self.current_route_index + 1}')
            print(f"✓ 已到达: {label} ({current_x}, {current_y})")
            self.advance_to_next_waypoint()
            self.update_route_status()
    
    def draw_route_on_display(self, display_img, view_x1, view_y1, player_x, player_y):
        """
        在显示地图上绘制路线
        :param display_img: 当前显示的图像（BGR格式）
        :param view_x1, view_y1: 视野左上角在大地图的坐标
        :param player_x, player_y: 玩家在大地图的绝对坐标
        """
        if not self.current_route or self.current_route_index >= len(self.current_route['points']):
            return
        
        h, w = display_img.shape[:2]
        
        # 计算下一个航点
        next_waypoint = self.get_next_waypoint()
        if not next_waypoint:
            return
        
        # 计算最近的未来几个航点用于绘制路线
        future_points = self.calculate_nearest_route(player_x, player_y, num_points=5)
        
        if not future_points:
            return
        
        # 绘制从玩家位置到各个航点的连线
        prev_x = player_x - view_x1  # 转换为显示图像的相对坐标
        prev_y = player_y - view_y1
        
        for idx, point in enumerate(future_points):
            curr_x = point['x'] - view_x1
            curr_y = point['y'] - view_y1
            
            # 检查点是否在视野内
            if 0 <= curr_x < w and 0 <= curr_y < h:
                # 绘制连线（青色虚线）
                if 0 <= prev_x < w and 0 <= prev_y < h:
                    cv2.line(display_img, (int(prev_x), int(prev_y)), (int(curr_x), int(curr_y)),
                             (0, 255, 255), 2, lineType=cv2.LINE_AA)
                    # 绘制箭头
                    angle = np.arctan2(curr_y - prev_y, curr_x - prev_x)
                    arrow_len = 10
                    arrow_angle = np.pi / 6
                    pt1 = (int(curr_x - arrow_len * np.cos(angle - arrow_angle)),
                           int(curr_y - arrow_len * np.sin(angle - arrow_angle)))
                    pt2 = (int(curr_x - arrow_len * np.cos(angle + arrow_angle)),
                           int(curr_y - arrow_len * np.sin(angle + arrow_angle)))
                    cv2.line(display_img, pt1, (int(curr_x), int(curr_y)), (0, 255, 255), 2)
                    cv2.line(display_img, pt2, (int(curr_x), int(curr_y)), (0, 255, 255), 2)
                
                # 绘制航点圆圈
                cv2.circle(display_img, (int(curr_x), int(curr_y)), 8, (0, 255, 255), 2)
                
                # 绘制序号文字
                label = str(idx + 1)
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.5
                thickness = 2
                
                # 文字阴影
                cv2.putText(display_img, label, (int(curr_x) + 12, int(curr_y) - 12),
                            font, font_scale, (0, 0, 0), thickness + 1)
                # 文字主体
                cv2.putText(display_img, label, (int(curr_x) + 11, int(curr_y) - 13),
                            font, font_scale, (0, 255, 255), thickness)
                
                prev_x, prev_y = curr_x, curr_y
        
        # 绘制采集范围圈（黄色虚线）
        picking_radius_px = self.picking_radius
        cv2.circle(display_img, (int(prev_x), int(prev_y)), picking_radius_px,
                   (0, 255, 255), 1, lineType=cv2.LINE_AA)


if __name__ == "__main__":

    run_selector_if_needed(force=True)
    root = tk.Tk()
    app = AIMapTrackerApp(root)
    
    # 绑定窗口关闭事件
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    root.mainloop()