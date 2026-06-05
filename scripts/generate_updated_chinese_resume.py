from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


OUT = Path("output/pdf/Zhiming_Liu_中文更新版.pdf")
W, H = A4

FONT_DIR = Path("/Applications/Microsoft Word.app/Contents/Resources/DFonts")
pdfmetrics.registerFont(TTFont("Deng", str(FONT_DIR / "Deng.ttf")))
pdfmetrics.registerFont(TTFont("DengB", str(FONT_DIR / "Dengb.ttf")))
pdfmetrics.registerFont(TTFont("Kaiti", str(FONT_DIR / "Kaiti.ttf")))
pdfmetrics.registerFont(TTFont("Times", str(FONT_DIR / "times.ttf")))
pdfmetrics.registerFont(TTFont("TimesB", str(FONT_DIR / "timesbd.ttf")))

LEFT = 36
RIGHT = W - 36
BODY = 10.6
SMALL = 10.0
LEADING = 14


def width(text, font="Deng", size=BODY):
    return pdfmetrics.stringWidth(text, font, size)


def draw(c, x, y, text, font="Deng", size=BODY):
    c.setFont(font, size)
    c.drawString(x, y, text)


def right(c, y, text, font="DengB", size=BODY):
    c.setFont(font, size)
    c.drawRightString(RIGHT, y, text)


def section(c, y, title):
    draw(c, LEFT, y, title, "Kaiti", 16)
    c.setLineWidth(1.3)
    c.line(LEFT, y - 3, RIGHT, y - 3)
    return y - 15


def wrap(text, max_w, font="Deng", size=BODY):
    out, line = [], ""
    for ch in text:
        trial = line + ch
        if width(trial, font, size) <= max_w or not line:
            line = trial
        else:
            out.append(line)
            line = ch
    if line:
        out.append(line)
    return out


def para(c, y, text, x=LEFT, max_w=None, font="Deng", size=BODY, leading=LEADING):
    if max_w is None:
        max_w = RIGHT - x
    for line in wrap(text, max_w, font, size):
        draw(c, x, y, line, font, size)
        y -= leading
    return y


def bullet(c, y, text, indent=18, font="Deng", size=BODY, leading=LEADING):
    bx = LEFT + indent
    tx = bx + 20
    draw(c, bx, y, "•", "TimesB", size)
    lines = wrap(text, RIGHT - tx, font, size)
    for i, line in enumerate(lines):
        draw(c, tx, y - i * leading, line, font, size)
    return y - max(1, len(lines)) * leading


def header(c):
    y = H - 54
    draw(c, LEFT, y, "刘志明", "Kaiti", 24)
    y -= 28
    draw(c, LEFT, y, "电话：", "DengB", 11.5)
    draw(c, LEFT + 35, y, "+852 9631 0816", "TimesB", 11.5)
    draw(c, LEFT + 141, y, "|", "Deng", 11.5)
    draw(c, LEFT + 157, y, "邮箱：", "DengB", 11.5)
    draw(c, LEFT + 199, y, "lzm200303@gmail.com", "TimesB", 11.5)
    draw(c, LEFT + 340, y, "|", "Deng", 11.5)
    draw(c, LEFT + 355, y, "Github:", "TimesB", 11.5)
    draw(c, LEFT + 408, y, "https://github.com/Lzm03", "TimesB", 11.5)
    return y - 28


def education(c, y):
    y = section(c, y, "教育背景")
    draw(c, LEFT, y, "布里斯托大学(英国)", "DengB", 11)
    draw(c, 230, y, "计算机科学", "DengB", 11)
    draw(c, 360, y, "本硕连读", "DengB", 11)
    right(c, y, "2021.09 - 2025.07", "DengB", 11)
    y -= 14
    draw(c, LEFT, y, "成绩：英国 二等一学位，绩点：3.6/4.0")
    y -= 14
    draw(c, LEFT, y, "核心课程：算法，数据驱动计算机科学，计算机系统，计算机图形学")
    y -= 15
    draw(c, LEFT, y, "香港理工大学(中国香港)", "DengB", 11)
    draw(c, 230, y, "元宇宙科技", "DengB", 11)
    draw(c, 360, y, "硕士", "DengB", 11)
    right(c, y, "2025.09 - 2026.07", "DengB", 11)
    y -= 14
    draw(c, LEFT, y, "核心课程：机器学习，自然语言处理，计算机视觉")
    return y - 24


def publications(c, y):
    y = section(c, y, "论文发表")
    pubs = [
        "[1] Z Liu, N Anantrasirichai, RMFAT: 循环多尺度特征大气湍流缓解模型，AAAI。",
        "[2] P Hill, Z Liu, A Achim, D Bull, N Anantrasirichai, DMAT: 大气湍流缓解与目标检测联合端到端框架，WACV。",
        "[3] Z Liu, P Hill, N Anantrasirichai, JDATT: 面向大气湍流缓解与目标检测的联合蒸馏框架，BMVC。",
        "[4] P. Hill, Z. Liu and N. Anantrasirichai, MAMAT: 基于 3D Mamba 的大气湍流去除及目标检测能力，AVSS 2025。",
    ]
    for p in pubs:
        y = para(c, y, p, font="Deng", size=9.5, leading=12)
    return y - 16


def research(c, y):
    y = section(c, y, "研究经历")
    draw(c, LEFT, y, "大气湍流缓解研究", "DengB", 11)
    right(c, y, "2025.05 - 至今", "DengB", 11)
    y -= 14
    draw(c, LEFT, y, "视觉信息实验室，布里斯托大学，英国布里斯托", "DengB", 10.5)
    y -= 15
    draw(c, LEFT, y, "研究内容:", "Kaiti", 11)
    y -= 14
    for item in [
        "聚焦基于深度学习的大气湍流缓解方法，以及畸变条件下的实时目标检测；研究内容包括循环网络、联合复原-检测框架和3D Mamba架构。",
        "开发 MAMAT，一套基于 3D Mamba 的湍流去除系统，具备良好的时序一致性并提升下游检测能力；发表于 AVSS 2025。",
        "设计 JDATT 联合蒸馏框架，将复原与检测知识融合，提升学生模型在湍流场景中的表现；以第一作者论文发表于 BMVC 2025。",
        "提出 DMAT 端到端框架，联合大气湍流缓解与目标检测，在严重畸变下显著提升检测鲁棒性；发表于 WACV 2026。",
        "构建 RMFAT 循环多尺度特征湍流缓解模型，针对模糊、几何畸变、抖动和时序不一致等问题进行建模；以第一作者论文发表于 AAAI 2026。",
    ]:
        y = bullet(c, y, item, size=10.2, leading=13.2)
    return y - 18


def work(c, y):
    y = section(c, y, "实习经历")
    items = [
        ("视觉信息实验室", "研究助理", "布里斯托大学，英国布里斯托", "2025.05 - 2025.12", [
            "模型复现：复现基线模型，准备数据集，并搭建基准测试流程。",
            "实验执行：开展受控实验，并维护具备可复现配置的训练流程。",
            "研究支持：协助进行结果分析、模型优化和研究成果整理。",
        ]),
        ("Index Academy", "全栈开发工程师 - AI教育平台", "中国香港，九龙", "2025.09 - 至今", [
            "平台开发：为中小学开发 AI 驱动的学习平台。",
            "功能实现：实现全栈功能，包括 3D 角色创建、语音定制和课程内容集成。",
            "系统优化：提升系统稳定性与交互性能，支持实时、可用于课堂的 AI 教学体验。",
        ]),
        ("深圳市维佳科创科技有限公司", "游戏开发实习生", "中国深圳", "2024.06 - 2024.08", [
            "使用 Unity 设计面向幼儿的互动教育游戏。",
            "构建基于物理的交互、拖拽逻辑和实时反馈机制。",
            "使用 C# 编写场景交互逻辑和游戏玩法行为。",
        ]),
    ]
    for company, role, loc, date, bullets in items:
        draw(c, LEFT, y, company, "DengB", 11)
        draw(c, 315, y, loc, "DengB", 10.4)
        right(c, y, date, "DengB", 10.7)
        y -= 14
        draw(c, LEFT, y, role, "Kaiti", 10.8)
        y -= 14
        for item in bullets:
            y = bullet(c, y, item, size=10.2, leading=13)
        y -= 8
    return y


def projects(c, y):
    y = section(c, y, "项目经历")
    draw(c, LEFT, y, "校内项目", "DengB", 11)
    draw(c, 210, y, "大气湍流图像恢复与目标检测联合优化", "DengB", 11)
    right(c, y, "2024.12 - 2025.04", "DengB", 10.7)
    y -= 15
    y = para(c, y, "项目描述：大气湍流导致的长距离图像/视频失真（如波纹、模糊）严重影响目标识别与检测的准确性。现有方法（如 CNN、Transformer、3D Mamba 架构）虽能提升图像质量，但依赖复杂网络和大参数量，难以满足实时性需求。同时，主流检测模型（如 Faster R-CNN、YOLO）在湍流环境下计算开销大，导致实时性下降。", size=10.2, leading=13.2)
    draw(c, LEFT, y, "项目成果:", "Kaiti", 10.8)
    y -= 14
    for item in [
        "筛选出湍流数据集上 PSNR、SSIM 最优的恢复模型及 mAP 最优的检测模型。",
        "构建端到端联合训练系统，恢复质量（PSNR/SSIM）与检测精度（mAP）均接近或优于基线模型。",
        "通过对比实验验证联合框架优势：模型体积减少 10%，推理速度提升 30%，适用于边缘设备部署。",
    ]:
        y = bullet(c, y, item, size=10.0, leading=12.8)
    y -= 16

    draw(c, LEFT, y, "校内项目", "DengB", 11)
    draw(c, 220, y, "图像超分辨率方法对比研究", "DengB", 11)
    right(c, y, "2024.10 - 2024.11", "DengB", 10.7)
    y -= 15
    y = para(c, y, "项目描述：研究基于深度学习的图像超分辨率技术，对比 DIP、GAN 和 Deep Unfolding 在噪声和降分辨率下的性能。使用 DIV2K 数据集，评估细节恢复(LPIPS)、结构相似性(SSIM)和视觉质量(PSNR)。", size=10.2, leading=13.2)
    draw(c, LEFT, y, "项目成果:", "Kaiti", 10.8)
    y -= 14
    for item in [
        "DIP 在细节还原表现最优（PSNR 31.60/SSIM 0.9387）。",
        "GAN 生成图像感知质量最佳（LPIPS 0.3284）。",
        "Deep Unfolding 在噪声/降采样场景鲁棒性最强（PSNR 34.85/SSIM 0.9532）。",
    ]:
        y = bullet(c, y, item, size=10.0, leading=12.8)
    y -= 16

    draw(c, LEFT, y, "校内项目（6人小组）", "DengB", 11)
    draw(c, 240, y, "气味陷阱游戏", "DengB", 11)
    right(c, y, "2024.01 - 2024.05", "DengB", 10.7)
    y -= 15
    y = para(c, y, "项目描述：气味陷阱是一个多人在线游戏，背景设定在一个荒废的大学里，玩家可以扮演人类或变异芝士角色进行对战。游戏支持最多 20 人同时在线，强调策略和团队协作。", size=10.2, leading=13.2)
    draw(c, LEFT, y, "主要工作:", "Kaiti", 10.8)
    y -= 14
    for item in [
        "开发基于 Unity3D 和 C# 的多人在线对战游戏，支持 20 人同时在线。",
        "负责核心游戏逻辑：角色控制、技能系统和阵营交互逻辑。",
        "实现 Photon 引擎网络同步，优化匹配与实时对战体验，确保低延迟与稳定性。",
        "设计策略地图与气味可视化系统，通过 Unity 粒子系统动态模拟气味扩散。",
        "开发 UI 交互界面，实时显示体力条、技能冷却等关键信息，优化玩家操作体验。",
    ]:
        y = bullet(c, y, item, size=10.0, leading=12.8)
    return y - 18


def skills(c, y):
    y = section(c, y, "个人技能与荣誉")
    for item in [
        "外语能力：普通话（母语），英语（熟练），粤语（流利）",
        "编程技能：Python（numpy、pandas、scikit-learn、matplotlib、pytorch），C++，C#，Java，GoLand",
        "软件与工具：LaTeX，Markdown，Excel，Adobe Photoshop",
    ]:
        y = bullet(c, y, item, indent=0, size=10.5, leading=14)
    return y


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=A4)
    y = header(c)
    y = education(c, y)
    y = publications(c, y)
    y = research(c, y)
    y = work(c, y)
    c.showPage()
    y = H - 48
    y = projects(c, y)
    if y < 120:
        c.showPage()
        y = H - 48
    skills(c, y)
    c.save()
    print(OUT)


if __name__ == "__main__":
    main()
