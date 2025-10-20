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


def generate_document_with_gemini(template_content, qa_data, analysis_result):
    """Generate final specification document with structured approach"""
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
    "website_url": "Ministry website (e.g., https://moh.gov.my)"
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
    
    # Replace main tender title placeholders
    if values.get('tender_title_full'):
        title = values['tender_title_full']
        filled = filled.replace('{ ****TAJUK**** TENDER }', title)
        filled = filled.replace('{TAJUK TENDER}', title)
        filled = filled.replace('**{TAJUK TENDER}**', f"**{title}**")
    
    # Replace year
    if values.get('contract_year'):
        year = values['contract_year']
        filled = re.sub(r'\*\*\d{4}\s*\*\*', f"**{year}**", filled)
    
    # Replace procurement branch
    if values.get('procurement_branch'):
        filled = filled.replace(
            '# <-- data need to be insert start--> \nCawangan Perolehan Dan Aset, Jabatan Kesihatan Negeri Sarawak.\n# <-- end data need to be insert-->',
            values['procurement_branch'] + '.'
        )
    
    # Replace hospital code and name
    if values.get('hospital_name'):
        filled = filled.replace("'**HMIRI**", f"'**{values['hospital_name']}**")
        filled = filled.replace("HMIRI", values['hospital_name'])
    
    if values.get('hospital_full_name'):
        filled = filled.replace("Hospital Miri", values['hospital_full_name'])
    
    # Replace state
    if values.get('state'):
        state = values['state']
        filled = filled.replace('Sarawak iaitu', f"{state} iaitu")
        filled = filled.replace('Sarawak ', f"{state} ")
        filled = filled.replace('Negeri Sarawak', f"Negeri {state}")
    
    # Replace bank statement months
    if values.get('bank_statement_months'):
        filled = filled.replace(
            '# <--data need to be insert start-->\n(Jun 2025, Julai 2025 dan Ogos 2025)\n# <-- End data need to be insert-->',
            f"({values['bank_statement_months']})"
        )
    
    # Replace financial years (single)
    if values.get('financial_years_single'):
        filled = filled.replace(
            '# <--data need to be insert start-->\n(2024 atau 2023)\n# <-- End data need to be insert-->',
            f"({values['financial_years_single']})"
        )
    
    # Replace hardware/software/network descriptions
    if values.get('involves_hardware') or values.get('involves_software') or values.get('involves_network'):
        equipment_desc = "peralatan fizikal termasuklah semua jenis kabel dan aksesori yang berkaitan seperti **JADUAL 2**"
        filled = filled.replace(
            '# <--data need to be insert start-->\nperalatan fizikal termasuklah semua jenis kabel dan aksesori yang berkaitan seperti **JADUAL 2**;\n# <-- End data need to be insert-->',
            equipment_desc + ';'
        )
    
    # Handle conditional sections
    if not values.get('is_fta_compliant', True):
        # Remove FTA-specific sections
        filled = re.sub(
            r'# <-- options based on conditions start -->.*?# <-- end options based on conditions -->',
            '',
            filled,
            flags=re.DOTALL
        )
    
    # Remove all comment markers
    filled = re.sub(r'# <--data need to be insert start-->.*?\n', '', filled)
    filled = re.sub(r'# <-- End data need to be insert-->.*?\n', '', filled)
    filled = re.sub(r'# <-- end data need to be insert-->.*?\n', '', filled)
    filled = re.sub(r'# <-- this is instruction start-->.*?# <-- end of this instruction start-->', '', filled, flags=re.DOTALL)
    filled = re.sub(r'# <-- options based on conditions start -->.*?\n', '', filled)
    filled = re.sub(r'# <-- end options based on conditions -->.*?\n', '', filled)
    
    # Remove any remaining HTML-style comments
    filled = re.sub(r'<>.*?</>', '', filled, flags=re.DOTALL)
    
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
