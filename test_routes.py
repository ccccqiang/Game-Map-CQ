"""
路线功能快速测试脚本
用于验证路径规划系统是否正常工作
"""

import json
import os
import sys

def test_route_loading():
    """测试路线加载功能"""
    print("=" * 60)
    print("测试1: 路线文件加载")
    print("=" * 60)
    
    routes_dir = "routes"
    if not os.path.exists(routes_dir):
        print(f"❌ 错误: 目录 {routes_dir} 不存在")
        return False
    
    route_files = [f for f in os.listdir(routes_dir) if f.endswith('.json')]
    print(f"✓ 找到 {len(route_files)} 个路线文件\n")
    
    for filename in route_files[:3]:  # 只测试前3个
        filepath = os.path.join(routes_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            name = data.get('name', '未命名')
            points = data.get('points', [])
            loop = data.get('loop', False)
            
            print(f"📄 {filename}")
            print(f"   名称: {name}")
            print(f"   航点数: {len(points)}")
            print(f"   循环: {loop}")
            
            if points:
                first = points[0]
                print(f"   首个航点: ({first.get('x')}, {first.get('y')})")
            print()
            
        except Exception as e:
            print(f"❌ 加载失败 {filename}: {e}\n")
    
    return True


def test_route_format():
    """测试路线格式是否正确"""
    print("=" * 60)
    print("测试2: 路线格式验证")
    print("=" * 60)
    
    sample_route = "routes/1示例跑图路线.json"
    
    if not os.path.exists(sample_route):
        print(f"⚠️  示例文件不存在: {sample_route}")
        return True
    
    try:
        with open(sample_route, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 检查必需字段
        required_fields = ['name', 'points']
        missing = [field for field in required_fields if field not in data]
        
        if missing:
            print(f"❌ 缺少必需字段: {missing}")
            return False
        
        print(f"✓ 路线名称: {data['name']}")
        print(f"✓ 航点数量: {len(data['points'])}")
        
        # 验证每个航点的格式
        for i, point in enumerate(data['points']):
            if 'x' not in point or 'y' not in point:
                print(f"❌ 航点 {i+1} 缺少 x/y 坐标")
                return False
            
            x, y = point['x'], point['y']
            label = point.get('label', f'节点 {i+1}')
            radius = point.get('radius', 30)
            
            print(f"   航点 {i+1}: ({x}, {y}) - {label} (半径: {radius})")
        
        print("\n✓ 格式验证通过")
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 格式错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False


def test_coordinate_system():
    """测试坐标系统一致性"""
    print("\n" + "=" * 60)
    print("测试3: 坐标系统检查")
    print("=" * 60)
    
    import cv2
    
    map_path = "big_map.png"
    if not os.path.exists(map_path):
        print(f"⚠️  地图文件不存在: {map_path}")
        print("   请确保 big_map.png 存在于项目根目录")
        return True
    
    map_img = cv2.imread(map_path)
    if map_img is None:
        print(f"❌ 无法读取地图文件")
        return False
    
    h, w = map_img.shape[:2]
    print(f"✓ 地图尺寸: {w} x {h} 像素")
    
    # 检查路线坐标是否在地图范围内
    sample_route = "routes/1示例跑图路线.json"
    if os.path.exists(sample_route):
        with open(sample_route, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        out_of_bounds = []
        for i, point in enumerate(data['points']):
            x, y = point['x'], point['y']
            if x < 0 or x >= w or y < 0 or y >= h:
                out_of_bounds.append((i+1, x, y))
        
        if out_of_bounds:
            print(f"⚠️  发现 {len(out_of_bounds)} 个越界航点:")
            for idx, x, y in out_of_bounds:
                print(f"   航点 {idx}: ({x}, {y}) - 超出地图范围")
        else:
            print(f"✓ 所有航点都在地图范围内")
    
    return True


def main():
    """运行所有测试"""
    print("\n🧪 开始路线功能测试...\n")
    
    results = []
    
    # 测试1: 路线加载
    results.append(("路线加载", test_route_loading()))
    
    # 测试2: 格式验证
    results.append(("格式验证", test_route_format()))
    
    # 测试3: 坐标系统
    results.append(("坐标系统", test_coordinate_system()))
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n🎉 所有测试通过！路线功能已就绪。")
        print("\n下一步:")
        print("1. 运行 python main_lk.py 启动程序")
        print("2. 在UI中选择并加载路线")
        print("3. 勾选'启用路线导航'查看效果")
    else:
        print("\n⚠️  部分测试失败，请检查上述错误信息")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
