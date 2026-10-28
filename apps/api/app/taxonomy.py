"""EB-103 — Dữ liệu taxonomy chuẩn Tiếng Anh THPT.

Tên Unit Global Success đã đối chiếu với mục lục SGK:
- Lớp 10 & 12: đối chiếu mục lục SGK (NXB Giáo dục Việt Nam) qua nhiều nguồn trùng khớp.
- Lớp 11: đối chiếu bảng tổng hợp chương trình Global Success 11.
Code Unit theo quy ước Bước 1: gs{grade}_unit{n}  (VD: gs12_unit3).
"""

GLOBAL_SUCCESS_UNITS = {
    10: [
        "Family Life",
        "Humans and the Environment",
        "Music",
        "For a Better Community",
        "Inventions",
        "Gender Equality",
        "Viet Nam and International Organisations",
        "New Ways to Learn",
        "Protecting the Environment",
        "Ecotourism",
    ],
    11: [
        "A Long and Healthy Life",
        "The Generation Gap",
        "Cities of the Future",
        "ASEAN and Viet Nam",
        "Global Warming",
        "Preserving Our Heritage",
        "Education Options for School-Leavers",
        "Becoming Independent",
        "Social Issues",
        "The Ecosystem",
    ],
    12: [
        "Life Stories We Admire",
        "A Multicultural World",
        "Green Living",
        "Urbanisation",
        "The World of Work",
        "Artificial Intelligence",
        "The World of Mass Media",
        "Wildlife Conservation",
        "Career Paths",
        "Lifelong Learning",
    ],
}

# 15 dạng bài theo enum QuestionType ở Bước 1, mục 3.1
QUESTION_TYPES = [
    ("pronunciation", "Phát âm"),
    ("stress", "Trọng âm"),
    ("grammar_mc", "Ngữ pháp trắc nghiệm"),
    ("vocabulary_mc", "Từ vựng trắc nghiệm"),
    ("synonym", "Đồng nghĩa"),
    ("antonym", "Trái nghĩa"),
    ("word_formation", "Dạng từ"),
    ("communication", "Giao tiếp / Chức năng ngôn ngữ"),
    ("error_identification", "Tìm lỗi sai"),
    ("cloze", "Đọc điền từ"),
    ("reading_comprehension", "Đọc hiểu"),
    ("reading_announcement", "Đọc thông báo / tờ rơi"),
    ("sentence_arrangement", "Sắp xếp câu / đoạn / thư"),
    ("sentence_transformation", "Viết lại câu"),
    ("listening_mc", "Nghe trắc nghiệm"),
]

SKILLS = [
    ("listening", "Nghe"),
    ("reading", "Đọc"),
    ("writing", "Viết"),
    ("speaking", "Nói"),
    ("language_focus", "Ngôn ngữ (phát âm / từ vựng / ngữ pháp)"),
]

DIFFICULTIES = [
    ("NB", "Nhận biết"),
    ("TH", "Thông hiểu"),
    ("VD", "Vận dụng"),
    ("VDC", "Vận dụng cao"),
]

TOPICS = [
    ("family", "Family"),
    ("environment", "Environment"),
    ("technology", "Technology"),
    ("education", "Education"),
    ("culture", "Culture"),
    ("health", "Health"),
    ("career", "Career"),
    ("media", "Media"),
    ("community", "Community"),
    ("tourism", "Tourism"),
]


def build_tag_specs():
    """Trả list dict {kind, code, label, parent_code} — parent_code tra sau khi tạo parent."""
    specs = []
    for grade in (10, 11, 12):
        specs.append({"kind": "grade", "code": f"grade_{grade}",
                      "label": f"Lớp {grade}", "parent_code": None})
    specs.append({"kind": "textbook", "code": "global_success",
                  "label": "Global Success", "parent_code": None})
    for grade, units in GLOBAL_SUCCESS_UNITS.items():
        for i, title in enumerate(units, start=1):
            specs.append({
                "kind": "unit",
                "code": f"gs{grade}_unit{i}",
                "label": f"Unit {i}: {title}",
                "parent_code": f"grade_{grade}",
            })
    for code, label in QUESTION_TYPES:
        specs.append({"kind": "question_type", "code": code, "label": label, "parent_code": None})
    for code, label in SKILLS:
        specs.append({"kind": "skill", "code": code, "label": label, "parent_code": None})
    for code, label in DIFFICULTIES:
        specs.append({"kind": "difficulty", "code": code, "label": label, "parent_code": None})
    for code, label in TOPICS:
        specs.append({"kind": "topic", "code": f"topic_{code}", "label": label, "parent_code": None})
    return specs
