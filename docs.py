import os
import sys
import html
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Preformatted, Table, TableStyle, HRFlowable, PageBreak
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute and render total page count
    along with running header and footer.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count):
        self.saveState()
        if self._pageNumber > 1:
            # Running Top Header
            self.setFont("Helvetica-Bold", 7.5)
            self.setFillColor(colors.HexColor("#0F172A"))
            self.drawString(36, 808, "EX STUDIO PHOTOGRAPHY")
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawString(160, 808, "|  Passwordless Auth & Profile Onboarding API Specification")
            
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(36, 800, 559, 800)

        # Running Bottom Footer
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        self.line(36, 36, 559, 36)
        
        self.setFont("Helvetica-Bold", 7.5)
        self.setFillColor(colors.HexColor("#D97706"))
        self.drawString(36, 25, "EX STUDIO")
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(88, 25, "-- Capture • Share • Deliver  |  Frontend Integration Manual (React 19 + Vite)")
        
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.setFont("Helvetica-Bold", 7.5)
        self.setFillColor(colors.HexColor("#0F172A"))
        self.drawRightString(559, 25, page_str)
        self.restoreState()


def build_docs_pdf(pdf_path):
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=44,
        bottomMargin=44
    )

    styles = getSampleStyleSheet()

    style_cover_title = ParagraphStyle(
        'CoverTitle',
        fontName='Helvetica-Bold',
        fontSize=13.5,
        leading=16.5,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=2
    )
    style_cover_sub = ParagraphStyle(
        'CoverSub',
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#D97706"),
        spaceAfter=4
    )
    style_meta_badge = ParagraphStyle(
        'MetaBadge',
        fontName='Helvetica',
        fontSize=6.9,
        leading=9.5,
        textColor=colors.HexColor("#334155")
    )
    style_h1 = ParagraphStyle(
        'Heading1_Custom',
        fontName='Helvetica-Bold',
        fontSize=8.6,
        leading=11,
        textColor=colors.white,
        backColor=colors.HexColor("#0F172A"),
        borderPadding=(3, 6, 3, 6),
        spaceBefore=5,
        spaceAfter=3,
        keepWithNext=True
    )
    style_h2 = ParagraphStyle(
        'Heading2_Custom',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=3.5,
        spaceAfter=1.5,
        keepWithNext=True
    )
    style_normal = ParagraphStyle(
        'Normal_Custom',
        fontName='Helvetica',
        fontSize=7.2,
        leading=9.8,
        textColor=colors.HexColor("#334155"),
        spaceAfter=1.5
    )
    style_bullet = ParagraphStyle(
        'Bullet_Custom',
        fontName='Helvetica',
        fontSize=7.1,
        leading=9.3,
        textColor=colors.HexColor("#334155"),
        leftIndent=10,
        spaceAfter=1
    )
    style_code = ParagraphStyle(
        'Code_Custom',
        fontName='Courier',
        fontSize=6.2,
        leading=7.5,
        textColor=colors.HexColor("#0F172A"),
        backColor=colors.HexColor("#F8FAFC"),
        borderColor=colors.HexColor("#CBD5E1"),
        borderWidth=0.5,
        borderPadding=2.5,
        spaceBefore=1,
        spaceAfter=2
    )
    style_kv_label = ParagraphStyle(
        'KV_Label',
        fontName='Helvetica-Bold',
        fontSize=7.2,
        leading=9.2,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=2,
        spaceAfter=1,
        keepWithNext=True
    )

    story = []

    # ================= PAGE 1: OVERVIEW & REGISTRATION =================
    cover_table_data = [
        [Paragraph("EX STUDIO &bull; PASSWORDLESS AUTHENTICATION & PROFILE ONBOARDING", style_cover_title)],
        [Paragraph("FRONTEND API SPECIFICATION & INTEGRATION MANUAL  |  CAPTURE &bull; SHARE &bull; DELIVER", style_cover_sub)],
        [Paragraph("<b>Base URL:</b> http://&lt;host&gt;:8000/api/ &nbsp;&bull;&nbsp; <b>Auth:</b> Bearer JWT / Cookies &nbsp;&bull;&nbsp; <b>Flow:</b> Email &rarr; OTP &rarr; Auto-Register / Login &rarr; Step 3 of 3: Set Up Your Profile", style_meta_badge)]
    ]
    cover_table = Table(cover_table_data, colWidths=[523])
    cover_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 0.7, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(cover_table)
    story.append(Spacer(1, 2))

    # SECTION 1: OVERVIEW & ARCHITECTURAL JOURNEY
    story.append(Paragraph("1. COMPLETE USER AUTHENTICATION & PROFILE SETUP JOURNEY", style_h1))
    story.append(Paragraph("This specification defines the frontend API integration contract for the EX Studio passwordless authentication pipeline and the <b>'Step 3 of 3: Set Up Your Profile'</b> onboarding screen.", style_normal))
    
    flow_steps = [
        "<b>Step 1 &mdash; User Enters Email:</b> Client calls <code>POST /api/auth/passwordless/reg/send-otp/</code> (for signup) or <code>/login/send-otp/</code> (for signin). Backend dispatches a 6-digit passcode (valid 10 min) and returns <code>is_registered</code>.",
        "<b>Step 2 &mdash; User Submits OTP:</b> Client calls <code>POST /api/auth/passwordless/reg/verify-otp/</code> or <code>/login/verify-otp/</code>. Sets secure HTTP-only cookies and returns user profile data.",
        "<b>Step 3 &mdash; Step 3 of 3: Set Up Your Profile:</b> Frontend renders the onboarding screen (<i>'Tell us a bit about yourself to personalize your studio workspace'</i>). Photographer fills: Profile Picture (optional upload or URL), Your Name (required), Phone Number (optional), and Occupation (optional).",
        "<b>Step 4 &mdash; Enter Workspace:</b> User clicks <b>'Enter Workspace &rarr;'</b>. Client dispatches <code>POST /api/photographers/onboarding/</code>. Backend updates profile, marks <code>is_onboarded = True</code>, <code>onboarding_step = 3</code>, and frontend redirects directly to dashboard."
    ]
    for s in flow_steps:
        story.append(Paragraph(f"&bull;&nbsp; {s}", style_bullet))
    story.append(Spacer(1, 2))

    # SECTION 2: REGISTRATION PASSWORDLESS ENDPOINTS
    story.append(Paragraph("2. REGISTRATION PASSWORDLESS ENDPOINTS (/api/auth/passwordless/reg/)", style_h1))
    
    # 2.1
    story.append(Paragraph("2.1 Send Registration OTP", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#15803D'><b>POST</b></font> &nbsp;|&nbsp; <b>Endpoint:</b> &nbsp;<code>/api/auth/passwordless/reg/send-otp/</code> &nbsp;|&nbsp; <b>Auth:</b> &nbsp;None", style_normal))
    story.append(Paragraph("<b>Request Body (JSON):</b>", style_kv_label))
    story.append(Preformatted("""{\n  "email": "sarang@atelierstudio.com"\n}""", style_code))
    story.append(Paragraph("<b>Response (200 OK):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "message": "Verification code sent to your email for registration.",
  "email": "sarang@atelierstudio.com",
  "is_registered": false
}""", style_code))

    # 2.2
    story.append(Paragraph("2.2 Verify Registration OTP & Auto-Register", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#15803D'><b>POST</b></font> &nbsp;|&nbsp; <b>Endpoint:</b> &nbsp;<code>/api/auth/passwordless/reg/verify-otp/</code> &nbsp;|&nbsp; <b>Auth:</b> &nbsp;None", style_normal))
    story.append(Paragraph("<b>Request Body (JSON):</b>", style_kv_label))
    story.append(Preformatted("""{
  "email": "sarang@atelierstudio.com",
  "otp": "839201",
  "fullname": "Sarang Varma",      // Optional: Prefills user display name
  "role": "photographer"           // Optional: default "photographer"
}""", style_code))
    story.append(Paragraph("<b>Response (200 OK):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "message": "Account registered and logged in successfully.",
  "is_new_user": true,
  "user": {
    "id": 12,
    "unique_id": "40a597a7-33e1-4c6e-b3f8-62d26f98c92a",
    "username": "sarang_varma",
    "email": "sarang@atelierstudio.com",
    "fullname": "Sarang Varma",
    "role": "photographer",
    "is_email_verified": true
  }
}
// Note: Tokens set in secure HTTP-only cookies (access_token & refresh_token)""", style_code))

    # 2.3
    story.append(Paragraph("2.3 Resend Registration OTP", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#15803D'><b>POST</b></font> &nbsp;|&nbsp; <b>Endpoint:</b> &nbsp;<code>/api/auth/passwordless/reg/resend-otp/</code> &nbsp;|&nbsp; <b>Auth:</b> &nbsp;None", style_normal))
    story.append(Paragraph("<b>Request Body (JSON):</b>", style_kv_label))
    story.append(Preformatted("""{\n  "email": "sarang@atelierstudio.com"\n}""", style_code))
    story.append(Paragraph("<b>Response (200 OK):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "message": "A new verification code has been sent to your email.",
  "email": "sarang@atelierstudio.com",
  "is_registered": false
}""", style_code))

    story.append(PageBreak())

    # ================= PAGE 2: LOGIN & UNIFIED ENDPOINTS =================
    story.append(Paragraph("3. LOGIN PASSWORDLESS ENDPOINTS (/api/auth/passwordless/login/)", style_h1))

    # 3.1
    story.append(Paragraph("3.1 Send Login OTP", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#15803D'><b>POST</b></font> &nbsp;|&nbsp; <b>Endpoint:</b> &nbsp;<code>/api/auth/passwordless/login/send-otp/</code> &nbsp;|&nbsp; <b>Auth:</b> &nbsp;None", style_normal))
    story.append(Paragraph("<b>Request Body (JSON):</b>", style_kv_label))
    story.append(Preformatted("""{\n  "email": "sarang@atelierstudio.com"\n}""", style_code))
    story.append(Paragraph("<b>Response (200 OK):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "message": "Verification code sent to your email for login.",
  "email": "sarang@atelierstudio.com",
  "is_registered": true
}""", style_code))

    # 3.2
    story.append(Paragraph("3.2 Verify Login OTP & Authenticate", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#15803D'><b>POST</b></font> &nbsp;|&nbsp; <b>Endpoint:</b> &nbsp;<code>/api/auth/passwordless/login/verify-otp/</code> &nbsp;|&nbsp; <b>Auth:</b> &nbsp;None", style_normal))
    story.append(Paragraph("<b>Request Body (JSON):</b>", style_kv_label))
    story.append(Preformatted("""{\n  "email": "sarang@atelierstudio.com",\n  "otp": "839201"\n}""", style_code))
    story.append(Paragraph("<b>Response (200 OK):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "message": "Login successful.",
  "is_new_user": false,
  "user": {
    "id": 12,
    "unique_id": "40a597a7-33e1-4c6e-b3f8-62d26f98c92a",
    "username": "sarang_varma",
    "email": "sarang@atelierstudio.com",
    "fullname": "Sarang Varma",
    "role": "photographer",
    "is_email_verified": true
  }
}
// Note: Tokens set in secure HTTP-only cookies (access_token & refresh_token)""", style_code))

    # 3.3
    story.append(Paragraph("3.3 Resend Login OTP", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#15803D'><b>POST</b></font> &nbsp;|&nbsp; <b>Endpoint:</b> &nbsp;<code>/api/auth/passwordless/login/resend-otp/</code> &nbsp;|&nbsp; <b>Auth:</b> &nbsp;None", style_normal))
    story.append(Paragraph("<b>Request Body (JSON):</b>", style_kv_label))
    story.append(Preformatted("""{\n  "email": "sarang@atelierstudio.com"\n}""", style_code))
    story.append(Paragraph("<b>Response (200 OK):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "message": "A new verification code has been sent to your email.",
  "email": "sarang@atelierstudio.com",
  "is_registered": true
}""", style_code))
    story.append(Spacer(1, 2))

    # SECTION 4: SHORTHAND ALIASES
    story.append(Paragraph("4. CONVENIENCE SHORTHAND ALIASES (/api/auth/otp/)", style_h1))
    story.append(Paragraph("Global aliases that automatically route between login and registration based on account state:", style_normal))
    
    shorthand_rows = [
        [Paragraph("<b>Action</b>", style_kv_label), Paragraph("<b>Shorthand Endpoint</b>", style_kv_label), Paragraph("<b>Target View & Behavior</b>", style_kv_label)],
        [Paragraph("Send OTP", style_normal), Paragraph("<code>POST /api/auth/otp/send/</code>", style_normal), Paragraph("Dispatches 6-digit passcode; returns <code>is_registered</code>.", style_normal)],
        [Paragraph("Verify OTP", style_normal), Paragraph("<code>POST /api/auth/otp/verify/</code>", style_normal), Paragraph("Logs in existing user or auto-creates photographer profile.", style_normal)],
        [Paragraph("Resend OTP", style_normal), Paragraph("<code>POST /api/auth/otp/resend/</code>", style_normal), Paragraph("Invalidates stale code and dispatches fresh passcode.", style_normal)],
    ]
    shorthand_table = Table(shorthand_rows, colWidths=[70, 200, 253])
    shorthand_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0,0), (-1,-1), 0.4, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(shorthand_table)

    story.append(PageBreak())

    # ================= PAGE 3: ONBOARDING SCREEN & FRONTEND INTEGRATION =================
    story.append(Paragraph("5. STEP 3 OF 3: SET UP YOUR PROFILE & ONBOARDING API", style_h1))
    story.append(Paragraph("Directly implements the EX Studio onboarding screen: <b>'Set Up Your Profile'</b> (<i>'Tell us a bit about yourself to personalize your studio workspace.'</i>).", style_normal))

    # UI Element Table
    ui_table_data = [
        [Paragraph("<b>UI Element on Screen</b>", style_kv_label), Paragraph("<b>API Field Name</b>", style_kv_label), Paragraph("<b>Type & Requirements</b>", style_kv_label), Paragraph("<b>Screen Placeholder / Details</b>", style_kv_label)],
        [Paragraph("<b>Profile Picture</b>", style_normal), Paragraph("<code>avatar</code> (or <code>avatar_url</code>)", style_normal), Paragraph("File (≤5MB) or URL<br/><b>Optional / Not mandatory</b>", style_normal), Paragraph("Upload portrait or studio avatar (PNG, JPG, WEBP).", style_normal)],
        [Paragraph("<b>Your Name</b>", style_normal), Paragraph("<code>name</code>", style_normal), Paragraph("String &bull; <b>Required</b>", style_normal), Paragraph("Placeholder: <code>e.g. Sarang Varma</code>. Updates user & profile.", style_normal)],
        [Paragraph("<b>Phone Number (optional)</b>", style_normal), Paragraph("<code>phone</code>", style_normal), Paragraph("String &bull; Optional", style_normal), Paragraph("Placeholder: <code>+1 (555) 000-0000</code>.", style_normal)],
        [Paragraph("<b>Occupation</b>", style_normal), Paragraph("<code>occupation</code>", style_normal), Paragraph("String &bull; Optional", style_normal), Paragraph("Placeholder: <code>e.g. Wedding Photographer</code>.", style_normal)],
        [Paragraph("<b>Enter Workspace &rarr;</b>", style_normal), Paragraph("<code>onboarding_step</code>", style_normal), Paragraph("Integer (default: <code>3</code>)", style_normal), Paragraph("Submit action &rarr; sets <code>is_onboarded=True</code> and enters workspace.", style_normal)],
    ]
    ui_table = Table(ui_table_data, colWidths=[105, 110, 115, 193])
    ui_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#FEF3C7")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#F59E0B")),
        ('INNERGRID', (0,0), (-1,-1), 0.4, colors.HexColor("#FDE68A")),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(ui_table)
    story.append(Spacer(1, 1))

    # 5.1
    story.append(Paragraph("5.1 Inspect Current Onboarding State (GET)", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#1D4ED8'><b>GET</b></font> &nbsp;|&nbsp; <b>Endpoint:</b> &nbsp;<code>/api/photographers/onboarding/</code> &nbsp;|&nbsp; <b>Auth:</b> &nbsp;Bearer Token", style_normal))
    story.append(Paragraph("<b>Response (200 OK):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "is_onboarded": false,
  "onboarding_step": 1,
  "name": "Sarang Varma",
  "phone": "",
  "occupation": "",
  "avatar_url": ""
}""", style_code))

    # 5.2
    story.append(Paragraph("5.2 Submit Profile Setup & Complete Onboarding (POST)", style_h2))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=1, spaceAfter=2))
    story.append(Paragraph("<b>Method:</b> &nbsp;<font color='#15803D'><b>POST</b></font> &nbsp;|&nbsp; <b>Endpoints:</b> &nbsp;<code>/api/photographers/onboarding/</code> &nbsp;or&nbsp; <code>/api/photographers/onboarding/complete/</code>", style_normal))
    story.append(Paragraph("<b>Auth:</b> &nbsp;Bearer Token (Photographer) &nbsp;|&nbsp; <b>Content-Types:</b> &nbsp;<code>application/json</code> or <code>multipart/form-data</code>", style_normal))

    story.append(Paragraph("<b>Option A: JSON Payload (Without Custom Image File):</b>", style_kv_label))
    story.append(Preformatted("""{
  "name": "Sarang Varma",
  "phone": "+1 (555) 000-0000",
  "occupation": "Wedding Photographer",
  "onboarding_step": 3
}""", style_code))

    story.append(Paragraph("<b>Option B: Multipart/Form-Data Payload (With Profile Picture File):</b>", style_kv_label))
    story.append(Preformatted("""Content-Type: multipart/form-data

name: "Sarang Varma"
phone: "+1 (555) 000-0000"
occupation: "Wedding Photographer"
avatar: <binary image file (PNG/JPG/WEBP up to 5MB)>
onboarding_step: 3""", style_code))

    story.append(Paragraph("<b>Response (200 OK &mdash; Transitions User into Workspace):</b>", style_kv_label))
    story.append(Preformatted("""{
  "status": "success",
  "message": "Profile setup and onboarding completed successfully.",
  "is_onboarded": true,
  "onboarding_step": 3,
  "profile": {
    "id": 1,
    "name": "Sarang Varma",
    "phone": "+1 (555) 000-0000",
    "occupation": "Wedding Photographer",
    "avatar_url": "http://api.domain.com/media/photographer_profiles/avatar.jpg",
    "is_onboarded": true,
    "onboarding_step": 3,
    "storage_used_bytes": 0,
    "storage_limit_bytes": 128849018880
  },
  "user": {
    "id": 12,
    "username": "sarang_varma",
    "email": "sarang@atelierstudio.com",
    "fullname": "Sarang Varma",
    "phone": "+1 (555) 000-0000"
  }
}""", style_code))
    story.append(Spacer(1, 1))

    # SECTION 6: FRONTEND AUTH INTEGRATION SNIPPET
    story.append(Paragraph("6. FRONTEND (REACT 19 / VITE) INTEGRATION BEST PRACTICES", style_h1))
    story.append(Paragraph("&bull;&nbsp; <b>HTTP-Only Cookie Auth:</b> Auth tokens (<code>access_token</code> & <code>refresh_token</code>) are set as secure HTTP-only cookies on <code>/verify-otp/</code>. Enable <code>credentials: 'include'</code> in Axios / Fetch so cookies are transmitted automatically.", style_bullet))
    story.append(Paragraph("&bull;&nbsp; <b>Auth Header:</b> If using custom token headers, pass <code>Authorization: Bearer &lt;access_token&gt;</code> with authenticated requests.", style_bullet))
    story.append(Paragraph("&bull;&nbsp; <b>Route Protection:</b> Check <code>profile.is_onboarded</code>. If <code>false</code>, redirect to <code>/onboarding</code>; upon clicking 'Enter Workspace &rarr;', redirect to <code>/dashboard</code>.", style_bullet))
    story.append(Paragraph("&bull;&nbsp; <b>Rate Limits & Validity:</b> OTP endpoints enforce a 60 req/min throttle. Passcodes expire after 10 minutes.", style_bullet))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"[SUCCESS] Generated documentation PDF at: {pdf_path}")


if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_pdf = os.path.join(current_dir, "docs.pdf")
    build_docs_pdf(output_pdf)
