"""
获取数据集文件列表（不下载数据）

使用方法：
python get_file_list.py

会尝试通过API获取文件列表，你可以：
1. 查看数据集大小和文件数量
2. 复制文件列表到 sync_to_minio.py 的 FILES_TO_SYNC
3. 选择性同步部分文件
"""

try:
    from openxlab.dataset import login, info, get
except ImportError:
    import openxlab
    login = openxlab.login
    info = openxlab.dataset.info
    get = openxlab.dataset.get

# 配置
ODL_AK = 'your-opendatalab-access-key'
ODL_SK = 'your-opendatalab-secret-key'
DATASET_REPO = 'OpenDataLab/UT-Interaction'  # 修改为你的数据集

def parse_file_list_from_info_dict(info_dict):
    """
    从 info() 返回的字典中解析文件列表
    返回: (文件列表, 是否完整)
    """
    files = []
    is_complete = True
    
    if 'File List' not in info_dict:
        return files, True
    
    file_list = info_dict['File List']
    
    for directory, file_dict in file_list.items():
        if not isinstance(file_dict, dict):
            continue
        
        for filename, size in file_dict.items():
            if '...' in filename or 'Showing' in filename:
                is_complete = False
                continue
            
            if directory == '/':
                files.append(filename)
            else:
                dir_prefix = directory.strip('/')
                if '/' in filename:
                    files.append(f"{dir_prefix}/{filename}")
                else:
                    files.append(f"{dir_prefix}/{filename}")
    
    return files, is_complete


def try_get_file_list_from_api():
    """尝试通过各种 API 方法获取文件列表（不下载数据）"""
    
    # 注意: 不使用 get() 因为它会触发下载！
    
    print(f"\n尝试方法 1: 使用 list_data_files()...")
    try:
        from openxlab.dataset import list_data_files
        files = list_data_files(dataset_repo=DATASET_REPO)
        if files and len(files) > 0:
            print(f"✓ 成功！获取到 {len(files)} 个文件\n")
            return files, True
        print(f"  返回空列表")
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {e}")
    
    print(f"\n尝试方法 2: 使用 list_raw_files()...")
    try:
        from openxlab.dataset import list_raw_files
        files = list_raw_files(dataset_repo=DATASET_REPO)
        if files and len(files) > 0:
            print(f"✓ 成功！获取到 {len(files)} 个文件\n")
            return files, True
        print(f"  返回空列表")
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {e}")
    
    print(f"\n尝试方法 3: 使用 info() 解析文件列表...")
    try:
        info_dict = info(dataset_repo=DATASET_REPO)
        files, is_complete = parse_file_list_from_info_dict(info_dict)
        if files and len(files) > 0:
            print(f"✓ 成功！解析到 {len(files)} 个文件")
            if not is_complete:
                print(f"⚠ 注意：文件列表可能不完整（部分目录文件被省略）")
            print()
            return files, is_complete
        print(f"  未找到文件列表")
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {e}")
    
    return None, False

def main():
    print("="*70)
    print(f"获取数据集文件列表: {DATASET_REPO}")
    print("="*70)
    
    # 登录
    try:
        login(ak=ODL_AK, sk=ODL_SK)
        print("✓ 登录成功")
    except Exception as e:
        print(f"✗ 登录失败: {e}")
        return
    
    # 尝试通过 API 获取文件列表
    print("\n尝试通过 API 获取文件列表（不下载数据集）...")
    print("="*70)
    result = try_get_file_list_from_api()
    
    if result[0] is not None:
        files, is_complete = result
        
        # 成功获取文件列表
        print("="*70)
        print(f"✓ 文件列表获取成功！共 {len(files)} 个文件")
        if not is_complete:
            print(f"⚠ 注意：列表可能不完整（部分目录文件被省略）")
            print(f"   如需完整列表，请设置 AUTO_DOWNLOAD_FOR_LIST = True")
        print("="*70)
        
        # 显示文件列表
        print(f"\n文件列表:")
        print("-"*70)
        for i, file in enumerate(files, 1):
            print(f"{i:4d}. {file}")
        
        # 生成配置代码
        print(f"\n" + "="*70)
        print(f"复制以下内容到 sync_to_minio.py 的配置区域:")
        print("="*70)
        print(f"\nFILE_LIST_MODE = 'manual'")
        print(f"FILES_TO_SYNC = [")
        for file in files:
            print(f"    '{file}',")
        print(f"]")
        
        if not is_complete:
            print(f"\n# 注意：上面的列表可能不完整")
            print(f"# 如需同步所有文件，请设置:")
            print(f"# FILE_LIST_MODE = 'progressive'")
            print(f"# AUTO_DOWNLOAD_FOR_LIST = True")
        
        print()
        
    else:
        # 所有方法都失败（不应该发生，因为 info() 通常会成功）
        print("\n" + "="*70)
        print(f"⚠ 无法获取文件列表")
        print("="*70)
        print(f"\n请尝试:")
        print(f"1. 检查网络连接")
        print(f"2. 检查 AK/SK 是否正确")
        print(f"3. 访问 https://opendatalab.com 查看数据集")

if __name__ == "__main__":
    main()
