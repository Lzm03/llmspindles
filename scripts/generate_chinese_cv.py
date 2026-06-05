from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


OUT = "output/pdf/CV_中文.pdf"
W, H = A4

pdfmetrics.registerFont(TTFont("Songti", "/System/Library/Fonts/Supplemental/Songti.ttc", subfontIndex=0))
FONT = "Songti"


def text_width(text, size):
    return pdfmetrics.stringWidth(text, FONT, size)


def draw_left(c, x, y, text, size=8.3, bold=False):
    c.setFont(FONT, size)
    c.drawString(x, y, text)


def draw_right(c, x, y, text, size=8.3):
    c.setFont(FONT, size)
    c.drawRightString(x, y, text)


def draw_center(c, y, text, size=13):
    c.setFont(FONT, size)
    c.drawCentredString(W / 2, y, text)


def section(c, y, title):
    c.setFont(FONT, 9.4)
    c.drawString(21 * mm, y, title)
    return y - 12


def wrap_text(text, max_width, size):
    lines, line = [], ""
    for ch in text:
        trial = line + ch
        if text_width(trial, size) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = ch
    if line:
        lines.append(line)
    return lines


def bullet(c, x, y, text, max_width, size=8.1, leading=10.5):
    c.setFont(FONT, size)
    c.drawString(x, y, "▪")
    lines = wrap_text(text, max_width, size)
    tx = x + 13
    for i, line in enumerate(lines):
        c.drawString(tx, y - i * leading, line)
    return y - max(1, len(lines)) * leading


def line_pair(c, y, left, right, size=8.3):
    draw_left(c, 21 * mm, y, left, size)
    draw_right(c, W - 21 * mm, y, right, size)
    return y - 10.5


def make_page_one(c):
    y = H - 33
    draw_center(c, y, "刘志明（Jayden）", 13.8)
    y -= 15
    draw_center(c, y, "电话：+852 9631 0816 | 邮箱：lzm200303@gmail.com | GitHub：https://github.com/Lzm03", 7.8)
    y -= 23

    y = section(c, y, "教育经历")
    y = line_pair(c, y, "布里斯托大学，英国布里斯托", "2021年9月 - 2025年7月")
    y = line_pair(c, y, "计算机科学本硕连读工程硕士 | GPA：3.6/4.00", "", 8.3)
    y = line_pair(c, y, "核心课程：算法、数据驱动计算机科学、计算机系统、计算机图形学", "", 8.3)
    y -= 5
    y = line_pair(c, y, "香港理工大学，香港九龙", "2025年9月 - 2026年7月")
    y = line_pair(c, y, "元宇宙科技理学硕士", "", 8.3)
    y = line_pair(c, y, "核心课程：机器学习、自然语言处理、计算机视觉", "", 8.3)
    y -= 17

    y = section(c, y, "论文发表")
    pubs = [
        "[1] Z Liu, N Anantrasirichai, RMFAT：循环多尺度特征大气湍流缓解模型。AAAI人工智能会议论文集（AAAI）。",
        "[2] P Hill, Z Liu, A Achim, D Bull, N Anantrasirichai, DMAT：面向大气湍流缓解与目标检测联合任务的端到端框架。IEEE/CVF冬季计算机视觉应用会议（WACV）。",
        "[3] Z Liu, P Hill, N Anantrasirichai, JDATT：面向大气湍流缓解与目标检测的联合蒸馏框架，第36届英国机器视觉会议（BMVC）。",
        "[4] P. Hill, Z. Liu and N. Anantrasirichai, MAMAT：基于3D Mamba的大气湍流去除方法及其目标检测能力，2025 IEEE先进视觉与信号系统国际会议（AVSS）。",
    ]
    for p in pubs:
        for line in wrap_text(p, W - 42 * mm, 8.4):
            draw_left(c, 21 * mm, y, line, 7.7)
            y -= 9.8
    y -= 12

    y = section(c, y, "研究经历")
    y = line_pair(c, y, "大气湍流缓解研究", "2025年5月 - 至今")
    y = line_pair(c, y, "视觉信息实验室，布里斯托大学，英国布里斯托", "", 8.3)
    bullets = [
        "聚焦基于深度学习的大气湍流缓解方法，以及畸变条件下的实时目标检测；研究内容包括循环网络、联合复原-检测框架和3D Mamba架构。",
        "开发MAMAT，一套基于3D Mamba的湍流去除系统，具备良好的时序一致性并提升下游检测能力；发表于AVSS 2025。",
        "设计JDATT联合蒸馏框架，将复原与检测知识融合，以提升学生模型在湍流场景中的表现；以第一作者论文发表于BMVC 2025。",
        "提出DMAT端到端框架，用于联合大气湍流缓解与目标检测，在严重畸变下显著提升检测鲁棒性；发表于WACV 2026。",
        "构建RMFAT循环多尺度特征湍流缓解模型，针对模糊、几何畸变、抖动和时序不一致等问题进行建模；以第一作者论文发表于AAAI 2026。",
    ]
    for b in bullets:
        y = bullet(c, 23 * mm, y, b, W - 51 * mm, 8.1, 10.5)
    y -= 11

    y = section(c, y, "工作经历")
    y = line_pair(c, y, "视觉信息实验室", "布里斯托大学，英国布里斯托")
    y = line_pair(c, y, "研究助理", "2025年5月 - 2025年12月")
    for b in [
        "模型复现：复现基线模型，准备数据集，并搭建基准测试流程。",
        "实验执行：开展受控实验，并维护具备可复现配置的训练流程。",
        "研究支持：协助进行结果分析、模型优化和研究成果整理。",
    ]:
        y = bullet(c, 23 * mm, y, b, W - 51 * mm, 8.1, 10.5)


def make_page_two(c):
    y = H - 42
    y = line_pair(c, y, "Index Academy", "香港九龙")
    y = line_pair(c, y, "全栈开发工程师 - AI教育平台", "2025年9月 - 至今")
    for b in [
        "平台开发：为中小学开发AI驱动的学习平台。",
        "功能实现：实现全栈功能，包括3D角色创建、语音定制和课程内容集成。",
        "系统优化：提升系统稳定性与交互性能，支持实时、可用于课堂的AI教学体验。",
    ]:
        y = bullet(c, 23 * mm, y, b, W - 51 * mm, 8.1, 10.5)

    y -= 17
    y = line_pair(c, y, "深圳微加科创科技", "中国深圳")
    y = line_pair(c, y, "游戏开发实习生", "2024年6月 - 2024年8月")
    for b in [
        "玩法设计：使用Unity为低龄儿童设计互动教育游戏。",
        "功能实现：构建基于物理的交互、拖拽逻辑和实时反馈机制。",
        "C#开发：使用C#编写场景交互逻辑和游戏玩法行为。",
    ]:
        y = bullet(c, 23 * mm, y, b, W - 51 * mm, 8.1, 10.5)

    y -= 22
    y = section(c, y, "技能")
    y = line_pair(c, y, "语言：普通话（母语）、英语（熟练）、粤语（流利）", "", 8.3)
    y = line_pair(c, y, "编程语言：Python（numpy、pandas、scikit-learn、matplotlib、pytorch）、C++、C#、Java、GoLand", "", 8.3)
    y = line_pair(c, y, "软件与工具：LaTeX、Markdown、Excel、Adobe Photoshop", "", 8.3)


def main():
    c = canvas.Canvas(OUT, pagesize=A4)
    make_page_one(c)
    c.showPage()
    make_page_two(c)
    c.save()


if __name__ == "__main__":
    main()
