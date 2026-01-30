import streamlit as st
import pandas as pd
from datetime import date
from io import BytesIO

# ========== CONFIG ==========

COLS = {
    "age": "Date of Birth",                         
    "degree": "Degree",               
    "country": "Country of Citizenship",  
    "personal_statement": "Personal Statement",
    "self_sponsorship": "Self Sponsorship",
    "family_support": "Parent/Family Support",
    "private_loan": "Private Loan",
    "third_party_scholarship": "Scholarship From a Third Party",
    "other_sources": "Other Sources",     
}

HIGH_PRIORITY_COLUMNS = [
    "Name",
    "Last",
    "Cell Phone Number",
    "WhatsApp Phone Number",
    "Email",
    "Program of Interest",
    "Select A Term",
    "Country of Citizenship",
    "Score",
    "Category",
    "Reasons",
]

# Weights of point system (change to what fits best)
SELF_SPONSOR_WEIGHT = 18
FAMILY_SUPPORT_WEIGHT = 28  
PRIVATE_LOAN_WEIGHT = 24
EXTERNAL_SCHOLAR_CONFIRMED_WEIGHT = 14
EXTERNAL_SCHOLAR_PLANNED_WEIGHT = 8      
ASU_SCHOLAR_PENALTY = -15                 

EUROPE_COUNTRIES = [
    "united kingdom", "uk", "england", "ireland", "germany", "france",
    "italy", "spain", "portugal", "netherlands", "belgium", "sweden",
    "norway", "denmark", "finland", "switzerland", "austria", "poland",
    "greece", "czech", "hungary", "romania", "iceland"
]

CARIBBEAN_COUNTRIES = [
    # Big islands / common spellings
    "jamaica", "haiti", "dominican republic", "dr",
    "trinidad", "trinidad and tobago", "tobago",
    "barbados", "bahamas", "grenada", "st lucia", "saint lucia",
    "st vincent", "saint vincent", "st vincent and the grenadines",
    "antigua", "antigua and barbuda",
    "st kitts", "saint kitts", "st kitts and nevis", "saint kitts and nevis",
    "dominica",
    "cuba", "puerto rico",

    # Territories / common entries
    "guadeloupe", "martinique", "cayman", "cayman islands",
    "turks", "turks and caicos", "aruba", "curacao", "curaçao",
    "bonaire", "bermuda", "virgin islands", "u.s. virgin islands", "british virgin islands",
    "anguilla", "montserrat",
]

SCHOLARSHIP_NEED_KEYWORDS = [
    "scholarship", "financial aid", "bursary",
    "can't afford", "cannot afford",
    "need support", "help with fees", "help pay", "help me pay",
    "fund my studies", "sponsor me"
]

NEGATIVE_WORDS = {"", "none", "no", "no source", "nothing", "n/a", "na", "nil"}


# ============================


def normalize_age(raw):
    """
    Tries to turn various raw DOB / age formats into an age in years.

    Handles:
      - plain ages: 19, 22, "21"
      - birth years: 2003, "2001"
      - full dates: "Tuesday 8 March 2005", "2005-03-08", etc.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None

    s = str(raw).strip()
    current_year = date.today().year

    # 1) Try plain integer first (age or birth year)
    try:
        x = int(s)
        if 1900 <= x <= current_year:      # looks like birth year
            return current_year - x
        if 10 <= x <= 80:                  # looks like age
            return x
    except Exception:
        pass

    # 2) Try parsing full date (e.g. "Tuesday 8 March 2005")
    try:
        dt = pd.to_datetime(s, errors="raise", dayfirst=True)
        year = dt.year
        if 1900 <= year <= current_year:
            return current_year - year
    except Exception:
        pass

    # 3) Fallback: look for a 4-digit year anywhere in the string
    for token in s.split():
        if token.isdigit() and len(token) == 4:
            y = int(token)
            if 1900 <= y <= current_year:
                return current_year - y

    # Couldn't figure it out
    return None


def clean_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def has_degree_text(value) -> bool:
    """
    Treat any non-empty degree text that isn't 'none' / 'n/a' as having a degree.
    Works for things like 'BSc', 'MSc (Public Health)', 'SSCE', etc.
    """
    t = clean_text(value)
    if t in NEGATIVE_WORDS:
        return False
    return t != ""


def has_family_support_text(value) -> bool:
    """
    Any non-empty, non-'none' text that mentions family/relatives/guardians.
    Works for: 'Parents', 'Parents and family support',
    'Yes, my maternal uncle...', 'Family members', 'Yes' (in this field).
    """
    t = clean_text(value)
    if t in NEGATIVE_WORDS:
        return False
    family_keywords = [
        "parent", "parents", "family", "uncle", "aunt", "relative",
        "guardian", "grand", "spouse", "husband", "wife",
        "brother", "sister", "cousin", "father", "mother"
    ]
    if any(k in t for k in family_keywords):
        return True
    if "yes" in t:
        return True
    return False


def has_self_support_text(value) -> bool:
    """
    Look for genuine self-funding: 'self', 'self sponsored',
    'own savings', 'working and schooling', 'salary' etc.
    """
    t = clean_text(value)
    if t in NEGATIVE_WORDS:
        return False
    self_keywords = [
        "self", "own savings", "my savings", "saving",
        "working", "work and study", "work and schooling",
        "salary", "income", "job", "yes"
    ]
    return any(k in t for k in self_keywords)


def has_private_loan_text(value) -> bool:
    """
    Detects bank/study/student loan.
    """
    t = clean_text(value)
    if t in NEGATIVE_WORDS:
        return False
    loan_keywords = ["loan", "bank", "credit", "lender", "student loan", "study loan", "yes"]
    return any(k in t for k in loan_keywords)


def parse_scholarship_text(value):
    """
    Classify scholarship-related text into:
        - external_confirmed
        - external_planned
        - asu_school_scholarship
    based on keywords.
    """
    t = clean_text(value)
    if t in NEGATIVE_WORDS:
        return {"external_confirmed": False, "external_planned": False, "asu_school": False}

    # If the applicant simply answered "yes" (or "y"), treat as "plans" to obtain
    # a scholarship rather than confirmed details; this catches simple boolean fields
    # where users tick/enter "yes" without further detail.
    if t in {"yes", "y"}:
        return {"external_confirmed": False, "external_planned": True, "asu_school": False}

    # Any scholarship/bursary/grant/NSFAS/SASSA/etc.
    schol_keywords = [
        "scholar", "bursary", "grant", "nsfas", "sassa", "sponsor", "sponsorship", "fund"
    ]
    if not any(k in t for k in schol_keywords):
        return {"external_confirmed": False, "external_planned": False, "asu_school": False}

    # If text clearly mentions All Saints / school -> ASU scholarship
    if "all saints" in t or ("school" in t and "scholar" in t) or ("university" in t and "scholar" in t):
        return {"external_confirmed": False, "external_planned": False, "asu_school": True}

    # If they say they PLAN to apply/seek
    planned_words = ["plan", "planning", "apply", "applying", "seek", "seeking", "looking"]
    if any(w in t for w in planned_words):
        return {"external_confirmed": False, "external_planned": True, "asu_school": False}

    # Otherwise treat as external confirmed
    return {"external_confirmed": True, "external_planned": False, "asu_school": False}



def age_degree_points(age, has_degree: bool):
    """
    Returns:
        points (int)
        reasons (list[str])

    Always produces a reason — even when no points awarded.
    """
    if age is None:
        return 0, ["Age unknown (no points applied)"]

    points = 0
    reasons = []

    # --- Degree + Age conditions ---

    if has_degree and age >= 24:
        points += 17
        reasons.append("Has degree and age ≥ 24")

    elif has_degree and 21 <= age <= 23:
        points += 12
        reasons.append("Has degree and age 21–23")

    elif (not has_degree) and age >= 24:
        points += 7
        reasons.append("Age ≥ 24 without degree (may be financially independent)")

    else:
        # Explicit neutral explanation
        if has_degree:
            reasons.append(f"Has degree but age {age} (<21) — no maturity bonus")
        else:
            reasons.append(f"No degree and age {age} — no maturity bonus")

    return points, reasons



def country_priority_flag(country_raw: str):
    """
    Returns:
        is_region_top (bool), points (int), reasons (list[str])

    Canada / US / Europe / Caribbean are top priority regions.
    """
    if not isinstance(country_raw, str):
        return False, 0, []

    c = country_raw.strip().lower()
    reasons = []

    REGION_BONUS = 40  # keep same bonus

    # Canada
    if "canada" in c:
        reasons.append("From Canada — top priority region")
        return True, REGION_BONUS, reasons

    # USA
    if "united states" in c or "usa" in c or "u.s.a" in c or "america" in c:
        reasons.append("From USA — top priority region")
        return True, REGION_BONUS, reasons

    # Europe
    if any(e in c for e in EUROPE_COUNTRIES):
        reasons.append("From Europe — top priority region")
        return True, REGION_BONUS, reasons

    # Caribbean
    if any(k in c for k in CARIBBEAN_COUNTRIES):
        reasons.append("From Caribbean — top priority region")
        return True, REGION_BONUS, reasons

    return False, 0, reasons



def personal_statement_requests_school_scholarship(text: str) -> bool:
    if not isinstance(text, str):
        return False
    t = text.lower()
    return any(keyword in t for keyword in SCHOLARSHIP_NEED_KEYWORDS)


def score_row(row: pd.Series) -> pd.Series:
    score = 0
    reasons = []

    # -------- Self sponsorship (based on text) --------
    self_support_raw = row.get(COLS["self_sponsorship"])
    has_self = has_self_support_text(self_support_raw)
    if has_self:
        score += SELF_SPONSOR_WEIGHT
        reasons.append("Self funding from own work/savings")

    # -------- Family support (from Parent/Family Support + Other Sources) --------
    family_field = row.get(COLS["family_support"])
    other_sources_field = row.get(COLS["other_sources"])

    has_family = (
        has_family_support_text(family_field) or
        has_family_support_text(other_sources_field)
    )

    if has_family:
        score += FAMILY_SUPPORT_WEIGHT
        reasons.append("Parent/Family financial support identified")

    # -------- Private loan --------
    private_loan_raw = row.get(COLS["private_loan"])
    has_loan = has_private_loan_text(private_loan_raw)
    if has_loan:
        score += PRIVATE_LOAN_WEIGHT
        reasons.append("Private / bank loan arranged or intended")

    # -------- Third-party scholarship (non-ASU) + other sources --------
    third_party_info = parse_scholarship_text(row.get(COLS["third_party_scholarship"]))
    other_sources_info = parse_scholarship_text(row.get(COLS["other_sources"]))

    external_confirmed = third_party_info["external_confirmed"] or other_sources_info["external_confirmed"]
    external_planned = third_party_info["external_planned"] or other_sources_info["external_planned"]
    asu_school_scholar = third_party_info["asu_school"] or other_sources_info["asu_school"]

    if external_confirmed:
        score += EXTERNAL_SCHOLAR_CONFIRMED_WEIGHT
        reasons.append("Confirmed scholarship/bursary from external source")

    if external_planned:
        score += EXTERNAL_SCHOLAR_PLANNED_WEIGHT
        if EXTERNAL_SCHOLAR_PLANNED_WEIGHT > 0:
            reasons.append("Plans to apply for external scholarship/bursary")

    if ASU_SCHOLAR_PENALTY != 0 and asu_school_scholar:
        score += ASU_SCHOLAR_PENALTY
        reasons.append("Depends on scholarship from ASU/school")

    # -------- Age + degree --------
    deg_text = (
        row.get(COLS["degree"]) or
        row.get("Degree (2)") or
        row.get("Degree (3)")
    )

    has_deg = has_degree_text(deg_text)

    age_val = normalize_age(row.get(COLS["age"]))
    age_pts, age_reasons = age_degree_points(age_val, has_deg)
    score += age_pts
    reasons.extend(age_reasons)

    # -------- Country-based auto top priority --------
    is_region_top, c_pts, c_reasons = country_priority_flag(
        row.get(COLS["country"])
    )
    score += c_pts
    reasons.extend(c_reasons)

    # -------- Personal statement asking ASU for scholarship --------
    if personal_statement_requests_school_scholarship(
        row.get(COLS["personal_statement"])
    ):
        score -= 10
        reasons.append("Personal statement suggests need for ASU scholarship")

    # -------- Clamp score to 0–100 --------
    score = max(0, min(100, score))

    # -------- Category decision on 0–100 scale --------
    if is_region_top:
        # Region priority: still special label
        if score >= 70:
            category = "Top priority (Canada / US / Europe / Caribbean)"
        else:
            category = "High potential (Canada / US / Europe / Caribbean – funding weaker)"
    else:
        if score >= 70:
            category = "Top priority (Financially strong)"
        elif 50 <= score < 70:
            category = "High potential"
        elif 35 <= score < 50:
            category = "Medium potential"
        else:
            category = "Low / scholarship-dependent"

    return pd.Series({
        "ComputedAge": age_val,
        "Score": score,
        "Category": category,
        "Reasons": "; ".join(reasons),

        # extra flags so UI can filter
        "HasFamilySupport": has_family,
        "HasSelfSupport": has_self,
        "HasPrivateLoan": has_loan,
        "HasExternalScholarshipConfirmed": external_confirmed,
        "HasExternalScholarshipPlanned": external_planned,
        "HasASUScholarDependency": asu_school_scholar,
    })




def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.getvalue()


# ========== STREAMLIT UI ==========

st.title("All Saints University – Applicant Prioritization Tool")

st.write("Upload your Wufoo export (Excel `.xlsx` or `.csv`) to score and filter applicants.")

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

# -------- Deduplicate: keep most recent submission per applicant --------

    email_col = "Email"
    name_col = "Name"
    dob_col = "Date of Birth"
    time_col = "Date Created"  # change if your Wufoo column has a different name

    df_before_dedup = df.copy()

    # 1️⃣ Sort by submission time if available
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        df = df.sort_values(by=time_col)

    # 2️⃣ Primary dedupe by Email (most reliable unique identifier)
    if email_col in df.columns:
        df = df.drop_duplicates(subset=[email_col], keep="last")

    # 3️⃣ Fallback dedupe ONLY for rows missing email
    if all(col in df.columns for col in [name_col, dob_col]):
        no_email_mask = df[email_col].isna() | (df[email_col].str.strip() == "")
        df_no_email = df[no_email_mask].drop_duplicates(subset=[name_col, dob_col], keep="last")
        df_with_email = df[~no_email_mask]
        df = pd.concat([df_with_email, df_no_email])

    dedup_count = len(df_before_dedup) - len(df)

    if dedup_count > 0:
        st.info(f"Removed {dedup_count} duplicate submission(s) — keeping the most recent per applicant.")



    # Score applicants
    with st.spinner("Scoring applicants..."):
        results = df.apply(score_row, axis=1)
        df_scored = pd.concat([df, results], axis=1)
        

    st.subheader("Full Scored Applicants")
    
    st.write(f"Total applicants scored: {df_scored.shape[0]}")
    st.dataframe(df_scored)

    # High priority (score >= 50)
    high_priority = (
        df_scored[df_scored["Score"] >= 50]
        .sort_values(by="Score", ascending=False) # sort high to low
        .copy()
    )
    
    # Medium Priority (score 35-49)
    medium_priority = (
    df_scored[(df_scored["Score"] >= 35) & (df_scored["Score"] < 50)]
    .sort_values(by="Score", ascending=False) # sort high to low
    .copy()
)
    
    # Low Priority (score < 35)
    low_priority = (
    df_scored[df_scored["Score"] < 35]
    .sort_values(by="Score", ascending=False) # sort high to low
    .copy()
)
    

    # Region-top: Canada/US/Europe/Caribbean
    region_top_mask = df_scored["Category"].str.contains("Canada / US / Europe / Caribbean", na=False)
    region_top = (
    df_scored[region_top_mask]
    .sort_values(by="Score", ascending=False)
    .copy()
)
    
    st.write("#### Scoring complete. Below are the tables of prioritized applicants from highest to lowest.")

    st.markdown("### High/Top-Priority Applicants (Score ≥ 50)")
    st.write(f"Count: {high_priority.shape[0]}")
    st.dataframe(high_priority[HIGH_PRIORITY_COLUMNS] if all(
        c in high_priority.columns for c in HIGH_PRIORITY_COLUMNS
    ) else high_priority)

    st.markdown("### Medium-Priority Applicants (Score 35–49)")
    st.write(f"Count: {medium_priority.shape[0]}")
    st.dataframe(medium_priority[HIGH_PRIORITY_COLUMNS] if all(
        c in medium_priority.columns for c in HIGH_PRIORITY_COLUMNS
    ) else medium_priority)
    
    st.markdown("### Region-Top Applicants (Canada / US / Europe / Caribbean)")
    st.write(f"Count: {region_top.shape[0]}")
    st.dataframe(region_top)

    st.markdown("### Low-Priority Applicants (Score < 35)")
    st.write(f"Count: {low_priority.shape[0]}")
    st.dataframe(low_priority[HIGH_PRIORITY_COLUMNS] if all(
        c in low_priority.columns for c in HIGH_PRIORITY_COLUMNS
    ) else low_priority)
    
     # ---- Parent-funded but Low-priority applicants ----
    parent_funded_only_low = df_scored[
        (df_scored["Category"] == "Low / scholarship-dependent") &
        (df_scored["HasFamilySupport"] == True) &
        (df_scored["HasSelfSupport"] == False) &
        (df_scored["HasPrivateLoan"] == False) &
        (df_scored["HasExternalScholarshipConfirmed"] == False) &
        (df_scored["HasExternalScholarshipPlanned"] == False)
    ].copy()

    st.markdown("### Parent-funded but scored as LOW priority")
    st.write(f"Count: {parent_funded_only_low.shape[0]}")

    if not parent_funded_only_low.empty:
        cols_for_review = [
            c for c in [
                "Name",
                "Last",
                "Country of Citizenship",
                "Parent/Family Support",
                "Other Sources",
                "Score",
                "Category",
                "Reasons",
            ] if c in parent_funded_only_low.columns
        ]
        st.dataframe(parent_funded_only_low[cols_for_review])

    else:
        st.caption("No applicants are parent-funded *only* and still in Low priority.")
    
    
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
    
    # medium priority only (selected columns + reasons)
    mp_cols = [c for c in HIGH_PRIORITY_COLUMNS if c in medium_priority.columns]
    medium_priority_export = medium_priority[mp_cols] if mp_cols else medium_priority
    
    # low priority only (selected columns + reasons)
    lp_cols = [c for c in HIGH_PRIORITY_COLUMNS if c in low_priority.columns]
    low_priority_export = low_priority[lp_cols] if lp_cols else low_priority
    
   

    st.download_button(
        label="📥 Download high/top-priority (Score ≥ 50)",
        data=to_excel_bytes(high_priority_export),
        file_name="asu_high_priority_50plus.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    
    st.download_button(
        label="📥 Download medium-priority (Score ≥ 35)",
        data=to_excel_bytes(medium_priority_export),
        file_name="asu_medium_priority_35plus.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    
    st.download_button(
        label="📥 Download low-priority (Score < 35)",
        data=to_excel_bytes(low_priority_export),
        file_name="asu_low_priority_below35.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    
    
    st.download_button(
        label="📥 Download parent-funded but LOW-priority list",
        data=to_excel_bytes(parent_funded_only_low[cols_for_review]),
        file_name="asu_parent_funded_low_priority.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Region-top download
    st.download_button(
        label="📥 Download region-top (Canada / US / Europe / Caribbean)",
        data=to_excel_bytes(region_top),
        file_name="asu_region_top.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.info("To get a PDF, open any downloaded Excel file, or just use your browser's **Print → Save as PDF** on the tables above.")
else:
    st.caption("Waiting for file upload...")
