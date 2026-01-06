import streamlit as st
import pandas as pd
from datetime import date
from io import BytesIO

# ========== CONFIG ==========

# Change these to match your Excel column headers
COLS = {
    "age": "Age",                         # age or birth year
    "degree": "Has Degree",               # Yes / No
    "country": "Country of Citizenship",  # text
    "personal_statement": "Personal Statement",  # text
    "self_sponsorship": "Self Sponsorship",      # Yes / No
    "family_support": "Parent/Family Support",   # Yes / No
    "private_loan": "Private Loan",             # Yes / No
    "third_party_scholarship": "Third Party Scholarship"  # Yes / No
}

# Columns to show in high-priority export
HIGH_PRIORITY_COLUMNS = [
    "Name",
    "Last",
    "Cell Phone Number",
    "WhatsApp Phone Number",
    "Email",
    "Program of Interest",
    "Country of Citizenship",
    "Score",
    "Category",
    "Reasons"
]

EUROPE_COUNTRIES = [
    "united kingdom", "uk", "england", "ireland", "germany", "france",
    "italy", "spain", "portugal", "netherlands", "belgium", "sweden",
    "norway", "denmark", "finland", "switzerland", "austria", "poland",
    "greece", "czech", "hungary", "romania", "iceland"
]

SCHOLARSHIP_NEED_KEYWORDS = [
    "scholarship", "financial aid", "bursary",
    "can't afford", "cannot afford",
    "need support", "help with fees", "help pay", "help me pay",
    "fund my studies", "sponsor me"
]

# ============================


def is_yes(value) -> bool:
    if isinstance(value, str):
        v = value.strip().lower()
        return v in {"yes", "y", "true", "1"}
    if isinstance(value, (int, float)):
        return value == 1
    return False


def normalize_age(raw):
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        x = int(str(raw).split()[0])
    except Exception:
        return None

    current_year = date.today().year
    if 1900 <= x <= current_year:   # birth year
        return current_year - x
    if 10 <= x <= 80:               # age
        return x
    return None


def age_degree_points(age, has_degree: bool):
    if age is None:
        return 0, []

    points = 0
    reasons = []

    if has_degree and age >= 24:
        points += 2
        reasons.append("Has degree and age ≥ 24")
    elif has_degree and 21 <= age <= 23:
        points += 1
        reasons.append("Has degree and age 21–23")
    elif (not has_degree) and age >= 24:
        points += 1
        reasons.append("Age ≥ 24 (more likely to self-fund)")

    return points, reasons


def country_priority_flag(country_raw: str):
    """
    Returns:
        is_region_top (bool), points (int), reasons (list[str])
    Anyone from Canada / US / Europe is automatic top priority region.
    """
    if not isinstance(country_raw, str):
        return False, 0, []

    c = country_raw.strip().lower()
    reasons = []

    # Canada
    if "canada" in c:
        reasons.append("From Canada — automatic top priority region")
        return True, 3, reasons

    # USA
    if "united states" in c or "usa" in c or "u.s.a" in c or "america" in c:
        reasons.append("From USA — automatic top priority region")
        return True, 3, reasons

    # Europe
    if any(e in c for e in EUROPE_COUNTRIES):
        reasons.append("From Europe — automatic top priority region")
        return True, 3, reasons

    return False, 0, reasons


def personal_statement_requests_school_scholarship(text: str) -> bool:
    if not isinstance(text, str):
        return False
    t = text.lower()
    return any(keyword in t for keyword in SCHOLARSHIP_NEED_KEYWORDS)


def score_row(row: pd.Series) -> pd.Series:
    score = 0
    reasons = []

    # Self sponsorship
    if is_yes(row.get(COLS["self_sponsorship"])):
        score += 3
        reasons.append("Self sponsorship: YES")

    # Family support
    if is_yes(row.get(COLS["family_support"])):
        score += 2
        reasons.append("Parent/Family support: YES")

    # Private loan
    if is_yes(row.get(COLS["private_loan"])):
        score += 2
        reasons.append("Private loan arranged")

    # Third-party scholarship
    if is_yes(row.get(COLS["third_party_scholarship"])):
        score += 1
        reasons.append("Third-party scholarship (non-ASU)")

    # Age + degree
    has_deg = is_yes(row.get(COLS["degree"]))
    age_val = normalize_age(row.get(COLS["age"]))
    age_pts, age_reasons = age_degree_points(age_val, has_deg)
    score += age_pts
    reasons.extend(age_reasons)

    # Country-based auto top priority
    is_region_top, c_pts, c_reasons = country_priority_flag(
        row.get(COLS["country"])
    )
    score += c_pts
    reasons.extend(c_reasons)

    # Personal statement asking ASU for scholarship
    if personal_statement_requests_school_scholarship(
        row.get(COLS["personal_statement"])
    ):
        score -= 2
        reasons.append("Personal statement suggests need for ASU scholarship")

    # Category
    if is_region_top:
        category = "Top priority (Canada / US / Europe)"
    else:
        if score >= 8:
            category = "Top priority (Financially strong)"
        elif score >= 5:
            category = "High potential"
        elif score >= 3:
            category = "Medium potential"
        else:
            category = "Low / scholarship-dependent"

    return pd.Series({
        "ComputedAge": age_val,
        "Score": score,
        "Category": category,
        "Reasons": "; ".join(reasons)
    })


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


# ========== STREAMLIT UI ==========

st.title("All Saints University – Applicant Prioritization Tool")

st.write("Upload your Wufoo export (Excel `.xlsx`) to score and filter applicants.")

uploaded_file = st.file_uploader(
    "Upload applicant file (.xlsx or .csv)",
    type=["xlsx", "csv"]
)

if uploaded_file is not None:
    try:
        file_name = uploaded_file.name.lower()

        if file_name.endswith(".csv"):
            df = pd.read_csv(uploaded_file, dtype=str)
        else:
            df = pd.read_excel(uploaded_file, dtype=str)
    except Exception as e:
        st.error(f"Could not read Excel file: {e}")
        st.stop()

    st.success(f"Loaded {df.shape[0]} rows and {df.shape[1]} columns.")

    # Score applicants
    with st.spinner("Scoring applicants..."):
        results = df.apply(score_row, axis=1)
        df_scored = pd.concat([df, results], axis=1)

    st.subheader("Full Scored Applicants")
    st.dataframe(df_scored)

    # High priority (score >= 4)
    high_priority = df_scored[df_scored["Score"] >= 4].copy()

    # Region-top: Canada/US/Europe
    region_top_mask = df_scored["Category"].str.contains("Canada / US / Europe", na=False)
    region_top = df_scored[region_top_mask].copy()

    st.markdown("### High-Priority Applicants (Score ≥ 4)")
    st.write(f"Count: {high_priority.shape[0]}")
    st.dataframe(high_priority[HIGH_PRIORITY_COLUMNS] if all(
        c in high_priority.columns for c in HIGH_PRIORITY_COLUMNS
    ) else high_priority)

    st.markdown("### Region-Top Applicants (Canada / US / Europe)")
    st.write(f"Count: {region_top.shape[0]}")
    st.dataframe(region_top)

    # Downloads
    st.markdown("### Download Results")

    # Full scored
    st.download_button(
        label="📥 Download full scored Excel",
        data=to_excel_bytes(df_scored),
        file_name="asu_applicants_scored.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # High priority only (selected columns + reasons)
    hp_cols = [c for c in HIGH_PRIORITY_COLUMNS if c in high_priority.columns]
    high_priority_export = high_priority[hp_cols] if hp_cols else high_priority

    st.download_button(
        label="📥 Download high-priority (Score ≥ 4)",
        data=to_excel_bytes(high_priority_export),
        file_name="asu_high_priority_4plus.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Region-top download
    st.download_button(
        label="📥 Download region-top (Canada / US / Europe)",
        data=to_excel_bytes(region_top),
        file_name="asu_region_top.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.info("To get a PDF, open any downloaded Excel file, or just use your browser's **Print → Save as PDF** on the tables above.")
else:
    st.caption("Waiting for file upload...")
