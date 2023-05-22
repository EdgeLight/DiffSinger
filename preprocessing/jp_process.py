import os
import textgrid
from tqdm import tqdm

# 获取当前脚本所在的路径
script_dir = os.getcwd()
textgrid_dir = os.path.join(script_dir, 'TextGrid2')
out_dir = os.path.join(script_dir, 'processed')
dict_file = os.path.join(script_dir, 'rules.txt')



# 检查路径是否已存在
if os.path.exists(out_dir):
    # 获取文件夹中的所有文件名
    file_names = os.listdir(out_dir)
    
    # 逐个删除文件
    for file_name in file_names:
        file_path = os.path.join(out_dir, file_name)
        os.remove(file_path)
else:
    # 创建文件夹
    os.makedirs(out_dir)
    

# 读取词典替换规则
replace_rules = {}
with open(dict_file, 'r') as f:
    for line in f:
        line = line.strip()
        if line:
            src, dest = line.split('\t')
            replace_rules[src] = dest

print(replace_rules)


# 统计元音和辅音替换次数的字典
consonant_count = {consonant: 0 for consonant in replace_rules.keys()}

# 统计文件总数
total_files = len([filename for filename in os.listdir(textgrid_dir) if filename.endswith('.TextGrid')])

# 遍历 TextGrid2 文件夹下的所有 .TextGrid 文件，并显示进度条
for filename in tqdm(os.listdir(textgrid_dir), total=total_files, desc='Processing',ncols=80):
    # 遍历 TextGrid2 文件夹下的所有 .TextGrid 文件
    if filename.endswith('.TextGrid'):
        # 构建 TextGrid 文件的完整路径
        textgrid_file = os.path.join(textgrid_dir, filename)

        # 读取 TextGrid 文件
        tg = textgrid.TextGrid.fromFile(textgrid_file)

        # 查找音素（phones）层
        phones_tier = None
        for tier in tg:
            if tier.name == 'phones':
                phones_tier = tier
                break

        # 替换音素标记
        for interval in phones_tier:
            for match, replace in replace_rules.items():
                if match in interval.mark:
                    consonant_count[match] += 1
                    interval.mark = interval.mark.replace(match, replace)

        # 保存修改后的 TextGrid 文件
        output_file = os.path.join(out_dir, f'{os.path.splitext(filename)[0]}.TextGrid')
        tg.write(output_file)


# 打印替换次数
print('替换如下:')
for consonant, replace in replace_rules.items():
    replace_count = consonant_count[consonant]
    print(f'{consonant}→{replace}: {replace_count}')

