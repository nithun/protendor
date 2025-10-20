import frappe
import json
import google.generativeai as genai
import re
from frappe import _

@frappe.whitelist()
def create_session(project, template):
    """Create a new specification session"""
    try:
        if not project or not template:
            return {
                'success': False,
                'error': 'Project and Template are required'
            }
        
        session = frappe.get_doc({
            'doctype': 'Specification Session',
            'project': project,
            'template': template,
            'status': 'Draft'
        })
        session.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return {
            'success': True,
            'session_name': session.name
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), 'Create Session Error')
        return {
            'success': False,
            'error': str(e)
        }


@frappe.whitelist()
def analyze_and_generate_questions(session_name):
    """Analyze template and approval docs, then generate questions"""
    try:
        session = frappe.get_doc('Specification Session', session_name)
        
        # Read template
        template = frappe.get_doc('Project Template', session.template)
        template_content = read_file_content(template.template_file)
        
        if not template_content:
            return {
                'success': False,
                'error': 'Template content is empty'
            }
        
        # Read approval documents
        project = frappe.get_doc('Projects', session.project)
        approval_contents = []
        for approval in project.approvals:
            if approval.approval_file:
                content = read_file_content(approval.approval_file)
                if content:
                    approval_contents.append(content)
        
        # Analyze with Gemini
        analysis_result = analyze_with_gemini(template_content, approval_contents)
        
        # Generate questions
        questions = generate_questions_with_gemini(analysis_result, template_content)
        
        # Save to session
        session.analysis_result = json.dumps(analysis_result, ensure_ascii=False)
        session.status = 'In Progress'
        session.questions = []
        
        for q in questions:
            session.append('questions', {
                'question_malay': q['question_english'],
                'question_type': q['question_type'],
                'select_options': json.dumps(q.get('select_options', []), ensure_ascii=False) if q['question_type'] == 'Select' else '',
                'answer': ''
            })
        
        session.save(ignore_permissions=True)
        frappe.db.commit()
        
        return {
            'success': True,
            'questions': [
                {
                    'question_malay': q.question_malay,
                    'question_type': q.question_type,
                    'select_options': q.select_options,
                    'answer': ''
                }
                for q in session.questions
            ]
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), 'Analyze Questions Error')
        return {
            'success': False,
            'error': str(e)
        }


@frappe.whitelist()
def save_answers(session_name, answers):
    """Save user answers"""
    try:
        answers = json.loads(answers) if isinstance(answers, str) else answers
        
        session = frappe.get_doc('Specification Session', session_name)
        
        for i, answer_data in enumerate(answers):
            if i < len(session.questions):
                session.questions[i].answer = answer_data.get('answer', '')
        
        session.save(ignore_permissions=True)
        frappe.db.commit()
        
        return {'success': True}
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), 'Save Answers Error')
        return {
            'success': False,
            'error': str(e)
        }


@frappe.whitelist()
def generate_specification(session_name):
    """Generate final specification document"""
    try:
        session = frappe.get_doc('Specification Session', session_name)
        template = frappe.get_doc('Project Template', session.template)
        
        # Read template
        template_content = read_file_content(template.template_file)
        
        # Prepare Q&A
        qa_data = []
        for q in session.questions:
            if q.answer:
                qa_data.append({
                    'question': q.question_malay,
                    'answer': q.answer
                })
        
        # Get analysis result
        analysis_result = json.loads(session.analysis_result) if session.analysis_result else {}
        
        # Generate document
        generated_content = generate_document_with_gemini(
            template_content,
            qa_data,
            analysis_result
        )
        
        # Create specification
        spec = frappe.get_doc({
            'doctype': 'Project Specification',
            'project': session.project,
            'session': session.name,
            'specification_content': generated_content
        })
        spec.insert(ignore_permissions=True)
        
        # Save as file
        file_doc = save_as_markdown_file(
            generated_content,
            f"{session.project}-specification.md",
            'Project Specification',
            spec.name
        )
        
        spec.markdown_file = file_doc.file_url
        spec.save(ignore_permissions=True)
        
        # Update session
        session.status = 'Completed'
        session.save(ignore_permissions=True)
        
        frappe.db.commit()
        
        return {
            'success': True,
            'spec_name': spec.name,
            'file_url': file_doc.file_url
        }
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), 'Generate Specification Error')
        return {
            'success': False,
            'error': str(e)
        }


# ============= Helper Functions =============

def read_file_content(file_url):
    """Read content from file"""
    try:
        if not file_url:
            return ""
            
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        file_path = file_doc.get_full_path()
        
        if file_path.endswith('.pdf'):
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ''
                for page in reader.pages:
                    text += page.extract_text() + '\n'
            return text
            
        elif file_path.endswith('.docx'):
            import docx
            doc = docx.Document(file_path)
            return '\n'.join([para.text for para in doc.paragraphs])
            
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
                
    except Exception as e:
        frappe.log_error(f"Error reading file {file_url}: {str(e)}")
        return ""


def get_gemini_client():
    """Get configured Gemini client"""
    settings = frappe.get_single('Gemini Settings')
    api_key = settings.get_password('api_key')
    
    if not api_key:
        frappe.throw('Gemini API key not configured in Gemini Settings')
    
    genai.configure(api_key=api_key)
    
    model_name = settings.model_name or 'models/gemini-2.5-pro'
    return genai.GenerativeModel(model_name)


def analyze_with_gemini(template_content, approval_contents):
    """Analyze template and approvals with Gemini"""
    model = get_gemini_client()
    
    approvals_text = '\n\n---\n\n'.join(approval_contents) if approval_contents else "No approval documents"
    
    prompt = f"""
You are an expert in Malaysian Government tender documents. Analyze the template and approval documents.

TEMPLATE (showing placeholders to fill):
{template_content[:6000]}

APPROVAL DOCUMENTS (containing actual project info):
{approvals_text[:6000]}

YOUR TASK:
1. Identify information that ALREADY EXISTS in the approval documents
2. Identify information that is STILL MISSING to complete the template
3. Note any conditional sections that depend on project type

RETURN ONLY JSON (no markdown formatting):
{{
    "found_info": {{
        "tender_title": "complete tender title from approval doc",
        "hospital_name": "hospital code or name",
        "state": "state name",
        "contract_duration": "duration in months",
        "is_fta_compliant": true or false,
        "involves_hardware": true or false,
        "involves_software": true or false,
        "involves_network": true or false,
        "ministry": "ministry name",
        "year": "2025 or current year"
    }},
    "missing_info": ["tender_closing_date", "financial_statement_months", "bank_statement_months", "specific_equipment_list"]
}}
"""
    
    response = model.generate_content(prompt)
    text = response.text.strip()
    
    # Clean JSON
    if '```json' in text:
        text = text.split('```json')[1].split('```')[0]
    elif '```' in text:
        text = text.split('```')[1].split('```')[0]
    
    return json.loads(text.strip())


def generate_questions_with_gemini(analysis_result, template_content):
    """Generate questions based on analysis"""
    model = get_gemini_client()
    
    missing_info = analysis_result.get('missing_info', [])
    found_info = analysis_result.get('found_info', {})
    
    prompt = f"""
Generate 8-12 clear questions in ENGLISH to collect missing information for a Malaysian Government tender.

INFORMATION ALREADY AVAILABLE (don't ask about these):
{json.dumps(found_info, indent=2, ensure_ascii=False)}

INFORMATION STILL NEEDED:
{json.dumps(missing_info, indent=2, ensure_ascii=False)}

QUESTION TYPES TO USE:
- Select: for limited choices (Yes/No, States, MOF Codes, etc.)
- Date: for date fields
- Number: for numeric values (budget, months, etc.)
- Text: for free text (descriptions, titles, etc.)

IMPORTANT:
- Questions must be clear and specific
- For Select questions, provide complete option lists
- For Malaysian states, use: ["Johor", "Kedah", "Kelantan", "Melaka", "Negeri Sembilan", "Pahang", "Pulau Pinang", "Perak", "Perlis", "Sabah", "Sarawak", "Selangor", "Terengganu", "WP Kuala Lumpur", "WP Labuan", "WP Putrajaya"]
- For MOF codes, use: ["210101 - Hardware (low end)", "210102 - Hardware (high end)", "210103 - Software", "210104 - Software Development", "210105 - Networking", "210106 - Data Management", "210107 - ICT Security", "210109 - Hardware/Software Leasing"]

RETURN ONLY JSON ARRAY (no markdown):
[
    {{
        "question_english": "What is the tender closing date?",
        "question_type": "Date",
        "select_options": []
    }},
    {{
        "question_english": "Select the applicable MOF registration codes:",
        "question_type": "Select",
        "select_options": ["210101 - Hardware (low end)", "210102 - Hardware (high end)", "210103 - Software"]
    }},
    {{
        "question_english": "What is the estimated contract value (RM)?",
        "question_type": "Number",
        "select_options": []
    }}
]
"""
    
    response = model.generate_content(prompt)
    text = response.text.strip()
    
    if '```json' in text:
        text = text.split('```json')[1].split('```')[0]
    elif '```' in text:
        text = text.split('```')[1].split('```')[0]
    
    return json.loads(text.strip())

def clean_markdown(content):
    """Clean and validate markdown formatting"""
    
    # === PHASE 0: Document-specific cleanup (Notion/Word artifacts) ===
    
    # Remove image references
    content = re.sub(r'!\[\]\([^\)]+\)\s*\n?', '', content)
    
    # Remove TOC links with about:blank
    content = re.sub(r'\[([^\]]+)\]\(about:blank[^\)]*\)', r'\1', content)
    
    # Fix strikethrough (remove ~~ markers)
    content = re.sub(r'~~([^~]*)~~', r'\1', content)
    
    # === PHASE 1: Fix escaped characters ===
    
    content = re.sub(r'\\\*\\\*', '**', content)
    content = re.sub(r'\\\*', '*', content)
    content = re.sub(r'\\_', '_', content)
    content = re.sub(r'\\\[', '[', content)
    content = re.sub(r'\\\]', ']', content)
    content = re.sub(r'\\\(', '(', content)
    content = re.sub(r'\\\)', ')', content)
    content = re.sub(r'\\\|', '|', content)
    content = re.sub(r'\\#', '#', content)
    
    # === PHASE 2: Clean malformed bold/italic ===
    
    content = re.sub(r'\*\*([^*]+?)\s+\*\*', r'**\1**', content)
    content = re.sub(r'\*\*\s+([^*]+?)\*\*', r'**\1**', content)
    content = re.sub(r'\*{3,}([^*]+?)\*{3,}', r'**\1**', content)
    
    # === PHASE 3: Fix incomplete bold/italic markers ===
    
    lines = content.split('\n')
    cleaned_lines = []
    
    for line in lines:
        if re.match(r'^\s*\|[\s\-:]+\|\s*$', line):
            cleaned_lines.append(line)
            continue
        
        bold_count = len(re.findall(r'\*\*', line))
        if bold_count % 2 != 0:
            line = line[::-1].replace('**', '', 1)[::-1]
        
        temp_line = line.replace('**', '__BOLD__')
        italic_count = temp_line.count('*')
        if italic_count % 2 != 0:
            idx = line.rfind('*')
            if idx != -1:
                line = line[:idx] + line[idx+1:]
        
        cleaned_lines.append(line)
    
    content = '\n'.join(cleaned_lines)
    
    # === PHASE 4: Clean tables ===
    
    table_lines = []
    in_table = False
    expected_cols = 0
    
    for line in content.split('\n'):
        if '|' in line and re.search(r'[-:]{2,}', line):
            in_table = True
            expected_cols = line.count('|') - 1
            table_lines.append(line)
        elif '|' in line and in_table:
            current_cols = line.count('|') - 1
            if current_cols < expected_cols:
                line = line.rstrip()
                if not line.endswith('|'):
                    line += ' |'
                while line.count('|') - 1 < expected_cols:
                    line = line.rstrip('|') + ' |'
            elif current_cols > expected_cols:
                parts = line.split('|')
                line = '|'.join(parts[:expected_cols + 2])
            table_lines.append(line)
        else:
            if in_table and '|' not in line:
                in_table = False
                expected_cols = 0
            table_lines.append(line)
    
    content = '\n'.join(table_lines)
    
    # === PHASE 5: Remove HTML/XML comments ===
    
    content = re.sub(r'<>.*?</>', '', content, flags=re.DOTALL)
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    content = re.sub(r'^\s*<>\s*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'^\s*</>\s*$', '', content, flags=re.MULTILINE)
    
    # === PHASE 6: Fix headers ===
    
    content = re.sub(r'^(#{1,6})([^\s#])', r'\1 \2', content, flags=re.MULTILINE)
    content = re.sub(r'^(#{1,6}\s+.+?)\s*#+\s*$', r'\1', content, flags=re.MULTILINE)
    
    # === PHASE 7: Clean links ===
    
    content = re.sub(r'\[([^\]]+)\]\s+\(([^\)]+)\)', r'[\1](\2)', content)
    
    # === PHASE 8: Fix specific document issues ===
    
    # Fix malformed brackets in tender titles
    content = re.sub(r'\{\*\*\[', r'**[', content)
    
    # Fix double closing brackets in URLs
    content = re.sub(r'(https?://[^\)]+)\)\)', r'\1)', content, flags=re.IGNORECASE)
    
    # Remove empty blockquotes
    content = re.sub(r'^\s*>\s*$', '', content, flags=re.MULTILINE)
    
    # === PHASE 9: Clean whitespace ===
    
    lines = content.split('\n')
    content = '\n'.join([line.rstrip() for line in lines])
    content = content.replace('\r\n', '\n')
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = content.rstrip() + '\n'
    
    return content


def validate_markdown(content):
    """Validate markdown syntax and return warnings"""
    warnings = []
    
    lines = content.split('\n')
    
    for i, line in enumerate(lines, 1):
        # Check for unmatched bold markers
        if line.count('**') % 2 != 0:
            warnings.append(f"Line {i}: Unmatched bold markers (**)")
        
        # Check for unmatched italic markers
        if line.count('*') % 2 != 0 and '**' not in line:
            warnings.append(f"Line {i}: Unmatched italic markers (*)")
        
        # Check for escaped characters that shouldn't be
        if r'\*\*' in line or r'\*' in line:
            warnings.append(f"Line {i}: Contains escaped asterisks (\\*)")
        
        # Check table formatting
        if '|' in line and line.strip().startswith('|'):
            cols = line.count('|') - 1
            if cols == 0:
                warnings.append(f"Line {i}: Malformed table row")
    
    # Check for proper table structure
    in_table = False
    prev_cols = 0
    
    for i, line in enumerate(lines, 1):
        if '|' in line and '---' in line:
            in_table = True
            prev_cols = line.count('|') - 1
        elif '|' in line and in_table:
            current_cols = line.count('|') - 1
            if current_cols != prev_cols:
                warnings.append(f"Line {i}: Inconsistent table columns (expected {prev_cols}, got {current_cols})")
        elif in_table and '|' not in line:
            in_table = False
    
    return warnings


def render_markdown_test(content):
    """Test if markdown renders correctly"""
    try:
        import markdown
        
        # Try to render
        html = markdown.markdown(content, extensions=['tables', 'fenced_code'])
        
        # Check if rendering produced reasonable output
        if len(html) < len(content) * 0.5:
            return False, "Markdown rendering produced suspiciously short output"
        
        if '<p>**' in html or '<p>\\*\\*' in html:
            return False, "Bold markers not rendered correctly"
        
        return True, "Markdown renders correctly"
        
    except Exception as e:
        return False, f"Markdown rendering error: {str(e)}"


def generate_document_with_gemini(template_content, qa_data, analysis_result):
    """Generate final specification document with comprehensive cleanup and validation"""
    model = get_gemini_client()
    
    # Step 1: Extract specific values from all available data
    found_info = analysis_result.get('found_info', {})
    user_answers = {item['question']: item['answer'] for item in qa_data}
    
    prompt_extract = f"""
You are processing data for a Malaysian Government tender document. Extract specific values from the information provided.

INFORMATION FROM APPROVAL DOCUMENTS:
{json.dumps(found_info, indent=2, ensure_ascii=False)}

USER PROVIDED ANSWERS:
{json.dumps(user_answers, indent=2, ensure_ascii=False)}

YOUR TASK:
Extract and return specific values needed to fill the tender template. Use information from BOTH sources above.

RETURN ONLY JSON (no markdown):
{{
    "tender_title_full": "Complete tender title in UPPER CASE Malay (e.g., PERKHIDMATAN SOKONGAN OPERASI...)",
    "tender_title_short": "Short version if different",
    "hospital_name": "Hospital name or code (e.g., HMIRI, TPC-OHCIS)",
    "hospital_full_name": "Full hospital/system name",
    "state": "State name or 'Seluruh Malaysia' if nationwide",
    "contract_duration_months": "Contract duration (e.g., 24, 30, 36)",
    "contract_year": "Year (e.g., 2025)",
    "is_fta_compliant": true or false,
    "involves_software": true or false,
    "involves_hardware": true or false,
    "involves_network": true or false,
    "involves_applications": true or false,
    "bank_statement_months": "Three months before closing (e.g., Julai 2025, Ogos 2025 dan September 2025)",
    "financial_years_single": "Last financial year (e.g., 2024 atau 2023)",
    "financial_years_triple": "Last 3 financial years (e.g., 2022, 2023 dan 2024)",
    "working_hours": "Working hours",
    "procurement_branch": "Procurement branch name",
    "mof_codes_list": ["210101", "210102"],
    "website_url": "Ministry website",
    "system_code": "System code",
    "system_full_name": "Full system name"
}}

If any information is not available, use reasonable defaults based on the context.
"""
    
    response = model.generate_content(prompt_extract)
    extracted_text = response.text.strip()
    
    # Clean JSON
    if '```json' in extracted_text:
        extracted_text = extracted_text.split('```json')[1].split('```')[0]
    elif '```' in extracted_text:
        extracted_text = extracted_text.split('```')[1].split('```')[0]
    
    try:
        values = json.loads(extracted_text.strip())
    except:
        frappe.log_error(f"JSON Parse Error: {extracted_text}")
        values = {}
    
    # Step 2: Fill template with Python string replacement
    filled = template_content
    
    # === PHASE 1: Replace all tender title variations ===
    if values.get('tender_title_full'):
        title = values['tender_title_full']
        
        replacements = [
            ('{ ****TAJUK**** TENDER }', title),
            ('{****TAJUK**** TENDER}', title),
            ('{ TAJUK TENDER }', title),
            ('{TAJUK TENDER}', title),
            ('**{TAJUK TENDER}**', f"**{title}**"),
            ('**{ TAJUK TENDER }**', f"**{title}**"),
            ('****{ TAJUK TENDER }**', f"**{title}**"),
        ]
        
        for old, new in replacements:
            filled = filled.replace(old, new)
    
    # === PHASE 2: Remove duplicate sections ===
    lines = filled.split('\n')
    cleaned_lines = []
    skip_next_lines = 0
    correct_duration = values.get('contract_duration_months', '')
    
    for i, line in enumerate(lines):
        # Skip if in skip mode
        if skip_next_lines > 0:
            skip_next_lines -= 1
            continue
        
        # Remove template example lines with different specifications
        if '[FTA(CPTPP)]' in line and 'MENGKAJI, MERANCANG, MEREKABENTUK' in line:
            skip_next_lines = 2
            continue
        
        # Check if line contains different contract duration
        if correct_duration and 'TEMPOH KONTRAK' in line:
            if f"{correct_duration} BULAN" not in line and re.search(r'\d+ BULAN', line):
                continue
        
        cleaned_lines.append(line)
    
    filled = '\n'.join(cleaned_lines)
    
    # === PHASE 3: Replace specific data points ===
    
    # Year
    if values.get('contract_year'):
        year = values['contract_year']
        filled = re.sub(r'\*\*\d{4}\s*\*\*', f"**{year}**", filled)
        filled = re.sub(r'\*\*\d{4}\*\*', f"**{year}**", filled)
    
    # Procurement branch
    if values.get('procurement_branch'):
        branch = values['procurement_branch']
        filled = re.sub(
            r'(penjelasan daripada\s*\n\n\n)(.*?)(\n\n)',
            f"\\1{branch}.\\3",
            filled,
            flags=re.DOTALL
        )
    
    # Hospital/System code
    if values.get('system_code'):
        code = values['system_code']
        filled = filled.replace("'**HMIRI**", f"'**{code}**")
        filled = filled.replace("**HMIRI**", f"**{code}**")
        filled = filled.replace("HMIRI", code)
    
    if values.get('system_full_name'):
        full_name = values['system_full_name']
        filled = filled.replace("**Hospital Miri**", f"**{full_name}**")
        filled = filled.replace("Hospital Miri", full_name)
    
    # State
    if values.get('state'):
        state = values['state']
        if state not in ['Seluruh Malaysia', 'Malaysia']:
            filled = filled.replace('Negeri Sarawak', f"Negeri {state}")
            filled = filled.replace('Sarawak iaitu', f"{state} iaitu")
            filled = filled.replace('di Negeri Sarawak', f"di Negeri {state}")
    
    # Bank statement months
    if values.get('bank_statement_months'):
        months = values['bank_statement_months']
        filled = re.sub(
            r'\((Jun|Julai|Ogos|September) 2025.*?\)',
            f"({months})",
            filled
        )
    
    # Financial years (single)
    if values.get('financial_years_single'):
        years = values['financial_years_single']
        filled = re.sub(r'\(2024 atau 2023\)', f"({years})", filled)
    
    # Financial years (triple) - for FTA
    if values.get('financial_years_triple'):
        years_triple = values['financial_years_triple']
        filled = re.sub(
            r'\(2022, 2023 dan 2024 atau 2021, 2022 dan 2023\)',
            f"({years_triple})",
            filled
        )
    
    # === PHASE 4: Handle conditional sections ===
    if not values.get('is_fta_compliant', True):
        # Remove FTA-specific sections
        filled = re.sub(
            r'# <-- options based on conditions start -->.*?# <-- end options based on conditions -->',
            '',
            filled,
            flags=re.DOTALL
        )
        # Remove LAMPIRAN 6 for CPTPP
        filled = re.sub(
            r'\|\s*\*\*LAMPIRAN\s*\*\*\*\*6\*\*.*?Country Of Origin.*?\|',
            '',
            filled,
            flags=re.IGNORECASE
        )
    
    # Remove PAT definition if not application-related
    if not values.get('involves_applications', False):
        filled = re.sub(
            r"Perkataan \*'Provisional Acceptance Test \(PAT\)'\*.*?// jika berkaitan applikasi",
            '',
            filled,
            flags=re.DOTALL
        )
    
    # === PHASE 5: Aggressive comment marker removal ===
    
    comment_patterns = [
        r'# <--data need to be insert start-->.*?\n',
        r'# <-- data need to be insert start-->.*?\n',
        r'# <--data need to be insert start -->.*?\n',
        r'# <-- data need to be insert start -->.*?\n',
        r'# <-- End data need to be insert-->.*?\n',
        r'# <-- end data need to be insert-->.*?\n',
        r'# <--End data need to be insert-->.*?\n',
        r'# <--end data need to be insert-->.*?\n',
        r'# <-- this is instruction start-->.*?# <-- end of this instruction start-->',
        r'# <--this is instruction start-->.*?# <--end of this instruction start-->',
        r'# <-- options based on conditions start -->.*?\n',
        r'# <--options based on conditions start-->.*?\n',
        r'# <-- end options based on conditions -->.*?\n',
        r'# <--end options based on conditions-->.*?\n',
        r'# <-- data need to be insert -->.*?\n',
        r'# <--data need to be insert-->.*?\n',
        r'//.*?applikasi.*?\n',
        r'// jika.*?\n',
    ]
    
    for pattern in comment_patterns:
        filled = re.sub(pattern, '', filled, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove any remaining lines that start with "# <--"
    filled = re.sub(r'^# <--.*?$', '', filled, flags=re.MULTILINE)
    
    # Remove HTML-style comments
    filled = re.sub(r'<>.*?</>', '', filled, flags=re.DOTALL)
    
    # === PHASE 6: Clean up extra whitespace ===
    
    # Remove lines with only whitespace
    filled = re.sub(r'^\s*$\n', '', filled, flags=re.MULTILINE)
    
    # Remove more than 3 consecutive newlines
    filled = re.sub(r'\n{4,}', '\n\n\n', filled)
    
    # === PHASE 7: Final verification pass ===
    
    # Check for any remaining placeholders
    remaining_placeholders = re.findall(r'\{[^}]*TAJUK[^}]*\}', filled, re.IGNORECASE)
    if remaining_placeholders:
        frappe.log_error(f"Remaining placeholders found: {remaining_placeholders}", "Template Fill Warning")
        if values.get('tender_title_full'):
            for placeholder in remaining_placeholders:
                filled = filled.replace(placeholder, values['tender_title_full'])
    
    # === PHASE 8: MARKDOWN CLEANUP AND VALIDATION ===
    
    frappe.log("Starting markdown cleanup and validation...")
    
    # Clean markdown formatting
    filled = clean_markdown(filled)
    
    # Validate markdown
    warnings = validate_markdown(filled)
    if warnings:
        # Log first 20 warnings
        warning_text = '\n'.join(warnings[:20])
        frappe.log_error(
            f"Markdown validation warnings ({len(warnings)} total):\n{warning_text}", 
            "Markdown Validation"
        )
        frappe.log(f"Markdown validation: {len(warnings)} warnings found")
    else:
        frappe.log("Markdown validation: No warnings")
    
    # Test rendering
    renders_ok, render_message = render_markdown_test(filled)
    if not renders_ok:
        frappe.log_error(f"Markdown rendering issue: {render_message}", "Markdown Rendering")
        frappe.log(f"Markdown rendering: FAILED - {render_message}")
    else:
        frappe.log(f"Markdown rendering: SUCCESS - {render_message}")
    
    # Final stats
    frappe.log(
        f"Document generated successfully: "
        f"{len(filled)} characters, "
        f"{len(warnings)} validation warnings, "
        f"Renders: {renders_ok}"
    )
    
    return filled


def generate_document_with_gemini_old(template_content, qa_data, analysis_result):
    """Generate final specification document with comprehensive cleanup"""
    model = get_gemini_client()
    
    # Step 1: Extract specific values from all available data
    found_info = analysis_result.get('found_info', {})
    user_answers = {item['question']: item['answer'] for item in qa_data}
    
    prompt_extract = f"""
You are processing data for a Malaysian Government tender document. Extract specific values from the information provided.

INFORMATION FROM APPROVAL DOCUMENTS:
{json.dumps(found_info, indent=2, ensure_ascii=False)}

USER PROVIDED ANSWERS:
{json.dumps(user_answers, indent=2, ensure_ascii=False)}

YOUR TASK:
Extract and return specific values needed to fill the tender template. Use information from BOTH sources above.

RETURN ONLY JSON (no markdown):
{{
    "tender_title_full": "Complete tender title in UPPER CASE Malay (e.g., PERKHIDMATAN SOKONGAN OPERASI DAN PENYELENGGARAAN...)",
    "tender_title_short": "Short version if different",
    "hospital_name": "Hospital name or code (e.g., HMIRI, Hospital Kuala Lumpur)",
    "hospital_full_name": "Full hospital name (e.g., Hospital Miri)",
    "state": "State name (e.g., Sarawak, Johor, Selangor)",
    "contract_duration_months": "Contract duration (e.g., 24, 30, 36)",
    "contract_year": "Year (e.g., 2025)",
    "is_fta_compliant": true or false,
    "involves_software": true or false,
    "involves_hardware": true or false,
    "involves_network": true or false,
    "involves_applications": true or false,
    "bank_statement_months": "Three months before closing (e.g., Jun 2025, Julai 2025 dan Ogos 2025)",
    "financial_years_single": "Last financial year (e.g., 2024 atau 2023)",
    "financial_years_triple": "Last 3 financial years (e.g., 2022, 2023 dan 2024 atau 2021, 2022 dan 2023)",
    "working_hours": "Working hours for the state (e.g., 8.00 pagi hingga 5.00 petang pada hari Isnin hingga Jumaat)",
    "procurement_branch": "Procurement branch name (e.g., Cawangan Perolehan Dan Aset, Jabatan Kesihatan Negeri Sarawak)",
    "mof_codes_list": ["210101", "210102", "210103"],
    "tender_closing_date": "Closing date if available",
    "website_url": "Ministry website (e.g., https://moh.gov.my)",
    "system_code": "System code if applicable (e.g., TPC-OHCIS, HMIRI)",
    "system_full_name": "Full system name if applicable"
}}

If any information is not available, use reasonable defaults based on the context.
"""
    
    response = model.generate_content(prompt_extract)
    extracted_text = response.text.strip()
    
    # Clean JSON
    if '```json' in extracted_text:
        extracted_text = extracted_text.split('```json')[1].split('```')[0]
    elif '```' in extracted_text:
        extracted_text = extracted_text.split('```')[1].split('```')[0]
    
    try:
        values = json.loads(extracted_text.strip())
    except:
        frappe.log_error(f"JSON Parse Error: {extracted_text}")
        values = {}
    
    # Step 2: Fill template with Python string replacement
    filled = template_content
    
    # === PHASE 1: Replace all tender title variations ===
    if values.get('tender_title_full'):
        title = values['tender_title_full']
        
        # Replace all variations of tender title placeholders
        replacements = [
            ('{ ****TAJUK**** TENDER }', title),
            ('{****TAJUK**** TENDER}', title),
            ('{ TAJUK TENDER }', title),
            ('{TAJUK TENDER}', title),
            ('**{TAJUK TENDER}**', f"**{title}**"),
            ('**{ TAJUK TENDER }**', f"**{title}**"),
            ('****{ TAJUK TENDER }**', f"**{title}**"),
        ]
        
        for old, new in replacements:
            filled = filled.replace(old, new)
    
    # === PHASE 2: Remove duplicate sections ===
    # Remove section between "# <-- data need to be insert -->" that appears near the top
    # This handles the duplicate tender title section
    lines = filled.split('\n')
    cleaned_lines = []
    skip_mode = False
    skip_line_count = 0
    
    for i, line in enumerate(lines):
        # Detect start of data insert block
        if '# <-- data need to be insert -->' in line or '# <--data need to be insert -->' in line:
            # Check if this is a duplicate section (appears early in document)
            if i < 20:  # If within first 20 lines, it's likely the duplicate
                skip_mode = True
                skip_line_count = 0
                continue
        
        # Detect end of data insert block
        if skip_mode and ('# <-- End data need to be insert-->' in line or '# <-- end data need to be insert-->' in line):
            skip_mode = False
            continue
        
        # Skip lines in skip mode
        if skip_mode:
            skip_line_count += 1
            if skip_line_count > 10:  # Safety: don't skip more than 10 lines
                skip_mode = False
            continue
        
        cleaned_lines.append(line)
    
    filled = '\n'.join(cleaned_lines)
    
    # === PHASE 3: Replace specific data points ===
    
    # Year
    if values.get('contract_year'):
        year = values['contract_year']
        filled = re.sub(r'\*\*\d{4}\s*\*\*', f"**{year}**", filled)
        filled = re.sub(r'\*\*\d{4}\*\*', f"**{year}**", filled)
    
    # Procurement branch
    if values.get('procurement_branch'):
        branch = values['procurement_branch']
        # Replace in the PERINGATAN section
        filled = re.sub(
            r'(penjelasan daripada\s*\n\n\n)(.*?)(\n\n)',
            f"\\1{branch}.\\3",
            filled,
            flags=re.DOTALL
        )
    
    # Hospital/System code
    if values.get('system_code'):
        code = values['system_code']
        filled = filled.replace("'**HMIRI**", f"'**{code}**")
        filled = filled.replace("**HMIRI**", f"**{code}**")
        filled = filled.replace("HMIRI", code)
    
    if values.get('system_full_name'):
        full_name = values['system_full_name']
        filled = filled.replace("**Hospital Miri**", f"**{full_name}**")
        filled = filled.replace("Hospital Miri", full_name)
    
    # State
    if values.get('state'):
        state = values['state']
        if state != 'Malaysia':  # Only replace if not nationwide
            filled = filled.replace('Negeri Sarawak', f"Negeri {state}")
            filled = filled.replace('Sarawak iaitu', f"{state} iaitu")
            filled = filled.replace('di Negeri Sarawak', f"di Negeri {state}")
    
    # Bank statement months
    if values.get('bank_statement_months'):
        months = values['bank_statement_months']
        filled = re.sub(
            r'\(Jun 2025, Julai 2025 dan Ogos 2025\)',
            f"({months})",
            filled
        )
        filled = re.sub(
            r'\(Julai 2025, Ogos 2025 dan September 2025\)',
            f"({months})",
            filled
        )
    
    # Financial years (single)
    if values.get('financial_years_single'):
        years = values['financial_years_single']
        filled = re.sub(
            r'\(2024 atau 2023\)',
            f"({years})",
            filled
        )
    
    # Financial years (triple) - for FTA
    if values.get('financial_years_triple'):
        years_triple = values['financial_years_triple']
        filled = re.sub(
            r'\(2022, 2023 dan 2024 atau 2021, 2022 dan 2023\)',
            f"({years_triple})",
            filled
        )
    
    # === PHASE 4: Handle conditional sections ===
    if not values.get('is_fta_compliant', True):
        # Remove FTA-specific sections more aggressively
        filled = re.sub(
            r'# <-- options based on conditions start -->.*?# <-- end options based on conditions -->',
            '',
            filled,
            flags=re.DOTALL
        )
        # Remove LAMPIRAN 6 for CPTPP
        filled = re.sub(
            r'\|\s*\*\*LAMPIRAN\s*\*\*\*\*6\*\*.*?Country Of Origin.*?\|',
            '',
            filled,
            flags=re.IGNORECASE
        )
    
    # Remove PAT definition if not application-related
    if not values.get('involves_applications', False):
        filled = re.sub(
            r"Perkataan \*'Provisional Acceptance Test \(PAT\)'\*.*?// jika berkaitan applikasi",
            '',
            filled,
            flags=re.DOTALL
        )
    
    # === PHASE 5: Aggressive comment marker removal ===
    
    # Remove all variations of data insert markers
    comment_patterns = [
        r'# <--data need to be insert start-->.*?\n',
        r'# <-- data need to be insert start-->.*?\n',
        r'# <--data need to be insert start -->.*?\n',
        r'# <-- data need to be insert start -->.*?\n',
        r'# <-- End data need to be insert-->.*?\n',
        r'# <-- end data need to be insert-->.*?\n',
        r'# <--End data need to be insert-->.*?\n',
        r'# <--end data need to be insert-->.*?\n',
        r'# <-- this is instruction start-->.*?# <-- end of this instruction start-->',
        r'# <--this is instruction start-->.*?# <--end of this instruction start-->',
        r'# <-- options based on conditions start -->.*?\n',
        r'# <--options based on conditions start-->.*?\n',
        r'# <-- end options based on conditions -->.*?\n',
        r'# <--end options based on conditions-->.*?\n',
        r'# <-- data need to be insert -->.*?\n',
        r'# <--data need to be insert-->.*?\n',
    ]
    
    for pattern in comment_patterns:
        filled = re.sub(pattern, '', filled, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove any remaining lines that start with "# <--"
    filled = re.sub(r'^# <--.*?$', '', filled, flags=re.MULTILINE)
    
    # Remove HTML-style comments
    filled = re.sub(r'<>.*?</>', '', filled, flags=re.DOTALL)
    
    # === PHASE 6: Clean up extra whitespace ===
    
    # Remove lines with only whitespace
    filled = re.sub(r'^\s*$\n', '', filled, flags=re.MULTILINE)
    
    # Remove more than 3 consecutive newlines
    filled = re.sub(r'\n{4,}', '\n\n\n', filled)
    
    # === PHASE 7: Final verification pass ===
    
    # Check for any remaining placeholders and log them
    remaining_placeholders = re.findall(r'\{[^}]*TAJUK[^}]*\}', filled, re.IGNORECASE)
    if remaining_placeholders:
        frappe.log_error(f"Remaining placeholders found: {remaining_placeholders}", "Template Fill Warning")
        # Try to replace them with the title anyway
        if values.get('tender_title_full'):
            for placeholder in remaining_placeholders:
                filled = filled.replace(placeholder, values['tender_title_full'])
    
    # Log success
    frappe.log(f"Document generated successfully. Length: {len(filled)} characters")
    
    return filled



def save_as_markdown_file(content, filename, attached_to_doctype, attached_to_name):
    """Save content as file in Frappe"""
    from frappe.utils.file_manager import save_file
    
    file_doc = save_file(
        filename,
        content.encode('utf-8'),
        attached_to_doctype,
        attached_to_name,
        is_private=0
    )
    
    return file_doc
