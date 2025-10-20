frappe.pages['spec-generator'].on_page_load = function(wrapper) {
    frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Specification Generator',
        single_column: true
    });

    new SpecGenerator(wrapper);
}

class SpecGenerator {
    constructor(wrapper) {
        this.wrapper = $(wrapper);
        this.page_content = this.wrapper.find('.page-content');
        this.current_step = 1;
        this.current_question_index = 0;
        this.session_name = null;
        this.questions = [];
        
        this.setup();
    }

    setup() {
        this.page_content.empty();
        this.render_html();
        this.init();
    }

    render_html() {
        const html = `
            <style>
            .spec-generator-page {
                max-width: 900px;
                margin: 40px auto;
                padding: 0 20px;
            }

            .page-header {
                margin-bottom: 30px;
            }

            .page-header h2 {
                font-size: 28px;
                font-weight: 600;
                color: #2c3e50;
            }

            .step-indicator {
                display: flex;
                justify-content: space-between;
                position: relative;
                margin-bottom: 40px;
            }

            .step-indicator::before {
                content: '';
                position: absolute;
                top: 20px;
                left: 50px;
                right: 50px;
                height: 2px;
                background: #e0e0e0;
                z-index: 0;
            }

            .step {
                display: flex;
                flex-direction: column;
                align-items: center;
                position: relative;
                z-index: 1;
                background: white;
                padding: 0 10px;
            }

            .step-number {
                width: 40px;
                height: 40px;
                border-radius: 50%;
                background: #e0e0e0;
                color: #666;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 16px;
                margin-bottom: 8px;
                transition: all 0.3s ease;
            }

            .step.active .step-number {
                background: #2490ef;
                color: white;
                box-shadow: 0 0 0 4px rgba(36, 144, 239, 0.2);
            }

            .step.completed .step-number {
                background: #28a745;
                color: white;
            }

            .step-label {
                font-size: 12px;
                color: #666;
                white-space: nowrap;
                font-weight: 500;
            }

            .step.active .step-label {
                color: #2490ef;
                font-weight: 600;
            }

            .card {
                border: 1px solid #dee2e6;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }

            .card-body {
                padding: 2rem;
            }

            .form-label {
                font-weight: 500;
                color: #495057;
                margin-bottom: 0.5rem;
            }

            .form-control, .form-select {
                border-radius: 8px;
                border: 1px solid #ced4da;
                padding: 0.625rem 0.875rem;
            }

            .btn {
                border-radius: 8px;
                padding: 0.625rem 1.25rem;
                font-weight: 500;
                transition: all 0.2s;
            }

            .btn-lg {
                padding: 0.875rem 1.5rem;
                font-size: 1rem;
            }

            .progress {
                background-color: #e9ecef;
                border-radius: 10px;
                overflow: hidden;
                height: 25px;
            }

            .progress-bar {
                background-color: #2490ef;
                font-weight: 600;
                transition: width 0.6s ease;
            }

            .question-card {
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                padding: 2rem;
                border-radius: 12px;
                border: 1px solid #dee2e6;
                margin-bottom: 1rem;
            }

            .question-text {
                font-size: 17px;
                font-weight: 500;
                margin-bottom: 1.25rem;
                color: #2c3e50;
                line-height: 1.6;
            }

            .loading-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(255, 255, 255, 0.95);
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                z-index: 9999;
                backdrop-filter: blur(4px);
            }

            .loading-overlay p {
                color: #2c3e50;
                margin-top: 1rem;
                font-size: 16px;
            }

            .download-buttons {
                display: flex;
                gap: 1rem;
                justify-content: center;
                flex-wrap: wrap;
            }

            .download-buttons .btn {
                min-width: 200px;
            }

            .alert {
                padding: 1rem;
                border-radius: 8px;
                margin-bottom: 1rem;
            }

            .alert-success {
                background-color: #d4edda;
                border: 1px solid #c3e6cb;
                color: #155724;
            }
            </style>

            <div class="spec-generator-page">
                
                <!-- Header -->
                <div class="page-header">
                    <h2>Specification Generator</h2>
                    <p class="text-muted">Build project specification documents easily</p>
                </div>

                <!-- Step Indicator -->
                <div class="step-indicator mb-4">
                    <div class="step active" data-step="1">
                        <div class="step-number">1</div>
                        <div class="step-label">Select Project</div>
                    </div>
                    <div class="step" data-step="2">
                        <div class="step-number">2</div>
                        <div class="step-label">Answer Questions</div>
                    </div>
                    <div class="step" data-step="3">
                        <div class="step-number">3</div>
                        <div class="step-label">Generate Document</div>
                    </div>
                </div>

                <!-- Step 1: Selection -->
                <div class="step-content" id="step-1">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="mb-3">Step 1: Select Project and Template</h5>
                            
                            <div class="form-group mb-3">
                                <label class="form-label">Project <span class="text-danger">*</span></label>
                                <select class="form-control form-select" id="project-select" required>
                                    <option value="">-- Select Project --</option>
                                </select>
                            </div>

                            <div class="form-group mb-4">
                                <label class="form-label">Template <span class="text-danger">*</span></label>
                                <select class="form-control form-select" id="template-select" required>
                                    <option value="">-- Select Template --</option>
                                </select>
                            </div>

                            <button class="btn btn-primary btn-lg" id="btn-start-analysis">
                                Start Analysis
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Step 2: Questions -->
                <div class="step-content" id="step-2" style="display: none;">
                    <div class="card">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-center mb-3">
                                <h5 class="mb-0">Step 2: Answer Questions</h5>
                                <span class="badge bg-primary fs-6" id="progress-badge">0/0</span>
                            </div>

                            <!-- Progress bar -->
                            <div class="progress mb-4">
                                <div class="progress-bar progress-bar-striped progress-bar-animated" 
                                     id="progress-bar" role="progressbar" style="width: 0%;">0%</div>
                            </div>

                            <!-- Question Container -->
                            <div id="question-container" class="mb-4"></div>

                            <!-- Navigation -->
                            <div class="d-flex justify-content-between gap-2">
                                <button class="btn btn-secondary" id="btn-prev-question" disabled>
                                    ← Previous
                                </button>
                                <button class="btn btn-primary" id="btn-next-question">
                                    Next →
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Step 3: Generate -->
                <div class="step-content" id="step-3" style="display: none;">
                    <div class="card">
                        <div class="card-body text-center py-5">
                            <h5 class="mb-4">Step 3: Generate Specification Document</h5>
                            
                            <div id="generation-status" class="mb-4">
                                <p class="text-muted">All questions have been answered. Click the button below to generate your document.</p>
                            </div>

                            <button class="btn btn-success btn-lg mb-4" id="btn-generate-spec">
                                Generate Document
                            </button>

                            <div id="download-section" style="display: none;">
                                <!-- Download content will be inserted here -->
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Loading Overlay -->
                <div class="loading-overlay" id="loading-overlay" style="display: none;">
                    <div class="spinner-border text-primary" style="width: 3rem; height: 3rem;" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p class="mt-3 fw-bold" id="loading-text">Please wait...</p>
                </div>

            </div>
        `;

        this.page_content.html(html);
    }

    init() {
        this.load_data();
        this.bind_events();
    }

    load_data() {
        // Load projects
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Projects',
                fields: ['name', 'project_name'],
                limit_page_length: 999,
                order_by: 'project_name asc'
            },
            callback: (r) => {
                if (r.message && r.message.length > 0) {
                    this.populate_select('#project-select', r.message, 'name', 'project_name');
                } else {
                    frappe.msgprint({
                        title: 'No Projects',
                        message: 'Please create a project first',
                        indicator: 'orange'
                    });
                }
            }
        });

        // Load templates
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Project Template',
                fields: ['name', 'template_name'],
                limit_page_length: 999,
                order_by: 'template_name asc'
            },
            callback: (r) => {
                if (r.message && r.message.length > 0) {
                    this.populate_select('#template-select', r.message, 'name', 'template_name');
                } else {
                    frappe.msgprint({
                        title: 'No Templates',
                        message: 'Please create a template first',
                        indicator: 'orange'
                    });
                }
            }
        });
    }

    populate_select(selector, data, value_field, label_field) {
        const $select = this.page_content.find(selector);
        data.forEach(item => {
            $select.append(
                $('<option>')
                    .val(item[value_field])
                    .text(item[label_field])
            );
        });
    }

    bind_events() {
        this.page_content.find('#btn-start-analysis').on('click', () => this.start_analysis());
        this.page_content.find('#btn-prev-question').on('click', () => {
            this.save_current_answer();
            this.show_previous_question();
        });
        this.page_content.find('#btn-next-question').on('click', () => {
            this.save_current_answer();
            this.show_next_question();
        });
        this.page_content.find('#btn-generate-spec').on('click', () => this.generate_specification());
    }

    start_analysis() {
        const project = this.page_content.find('#project-select').val();
        const template = this.page_content.find('#template-select').val();

        if (!project || !template) {
            frappe.msgprint({
                title: 'Error',
                message: 'Please select both project and template',
                indicator: 'red'
            });
            return;
        }

        this.show_loading('Analyzing template and approval documents...');

        frappe.call({
            method: 'pro_tender.api.create_session',
            args: { project, template },
            callback: (r) => {
                if (r.message && r.message.success) {
                    this.session_name = r.message.session_name;
                    this.analyze_and_generate_questions();
                } else {
                    this.hide_loading();
                    frappe.msgprint({
                        title: 'Error',
                        message: r.message?.error || 'Unknown error',
                        indicator: 'red'
                    });
                }
            },
            error: () => {
                this.hide_loading();
                frappe.msgprint('Error connecting to server');
            }
        });
    }

    analyze_and_generate_questions() {
        this.show_loading('Generating questions with Gemini AI...<br><small>This may take 30-60 seconds</small>');

        frappe.call({
            method: 'pro_tender.api.analyze_and_generate_questions',
            args: { session_name: this.session_name },
            callback: (r) => {
                this.hide_loading();
                if (r.message && r.message.success) {
                    this.questions = r.message.questions;
                    if (this.questions.length === 0) {
                        frappe.msgprint({
                            title: 'Complete',
                            message: 'All information is already available from approval documents.',
                            indicator: 'green'
                        });
                        this.go_to_step(3);
                    } else {
                        this.go_to_step(2);
                        this.render_question(0);
                    }
                } else {
                    frappe.msgprint({
                        title: 'Error',
                        message: r.message?.error || 'Error generating questions',
                        indicator: 'red'
                    });
                }
            },
            error: () => {
                this.hide_loading();
                frappe.msgprint('Gemini API Error. Please check your API key in Gemini Settings.');
            }
        });
    }

    render_question(index) {
        if (index < 0 || index >= this.questions.length) return;

        this.current_question_index = index;
        const q = this.questions[index];

        let input_html = '';

        switch(q.question_type) {
            case 'Text':
                input_html = `<input type="text" class="form-control" id="answer-input" 
                              value="${(q.answer || '').replace(/"/g, '&quot;')}" 
                              placeholder="Enter your answer">`;
                break;

            case 'Select':
                const options = JSON.parse(q.select_options || '[]');
                input_html = `<select class="form-control form-select" id="answer-input">
                    <option value="">-- Select --</option>
                    ${options.map(opt => 
                        `<option value="${opt}" ${q.answer === opt ? 'selected' : ''}>${opt}</option>`
                    ).join('')}
                </select>`;
                break;

            case 'Date':
                input_html = `<input type="date" class="form-control" id="answer-input" 
                              value="${q.answer || ''}">`;
                break;

            case 'Number':
                input_html = `<input type="number" class="form-control" id="answer-input" 
                              value="${q.answer || ''}" placeholder="Enter number">`;
                break;
        }

        const html = `
            <div class="question-card">
                <div class="question-text">${q.question_malay}</div>
                ${input_html}
            </div>
        `;

        this.page_content.find('#question-container').html(html);
        this.update_progress();
        this.update_navigation();
        
        setTimeout(() => this.page_content.find('#answer-input').focus(), 100);
    }

    save_current_answer() {
        const answer = this.page_content.find('#answer-input').val();
        if (this.current_question_index < this.questions.length) {
            this.questions[this.current_question_index].answer = answer;
        }
    }

    show_next_question() {
        if (this.current_question_index < this.questions.length - 1) {
            this.render_question(this.current_question_index + 1);
        } else {
            this.save_all_answers();
        }
    }

    show_previous_question() {
        if (this.current_question_index > 0) {
            this.render_question(this.current_question_index - 1);
        }
    }

    update_navigation() {
        this.page_content.find('#btn-prev-question').prop('disabled', this.current_question_index === 0);
        
        if (this.current_question_index === this.questions.length - 1) {
            this.page_content.find('#btn-next-question').html('Finish ✓');
        } else {
            this.page_content.find('#btn-next-question').html('Next →');
        }
    }

    update_progress() {
        const answered = this.questions.filter(q => q.answer && q.answer.trim()).length;
        const total = this.questions.length;
        const percentage = total > 0 ? Math.round((answered / total) * 100) : 0;

        this.page_content.find('#progress-badge').text(`${answered}/${total}`);
        this.page_content.find('#progress-bar')
            .css('width', `${percentage}%`)
            .text(`${percentage}%`);
    }

    save_all_answers() {
        this.show_loading('Saving answers...');

        frappe.call({
            method: 'pro_tender.api.save_answers',
            args: {
                session_name: this.session_name,
                answers: JSON.stringify(this.questions)
            },
            callback: (r) => {
                this.hide_loading();
                if (r.message && r.message.success) {
                    this.go_to_step(3);
                }
            }
        });
    }

    generate_specification() {
        this.show_loading('Generating document with Gemini AI...<br><small>This may take 1-2 minutes</small>');

        frappe.call({
            method: 'pro_tender.api.generate_specification',
            args: { session_name: this.session_name },
            callback: (r) => {
                this.hide_loading();
                if (r.message && r.message.success) {
                    this.show_download_links(r.message);
                    
                    let message = 'Document generated successfully!';
                    if (!r.message.pdf_generated) {
                        message += ' (Note: PDF generation failed, but Markdown is available)';
                    }
                    
                    frappe.show_alert({
                        message: message,
                        indicator: 'green'
                    }, 5);
                } else {
                    frappe.msgprint('Error: ' + (r.message?.error || 'Unknown'));
                }
            },
            error: (err) => {
                this.hide_loading();
                frappe.msgprint('Error generating specification: ' + err.message);
            }
        });
    }

    show_download_links(result) {
        const markdown_url = result.markdown_file_url;
        const pdf_url = result.pdf_file_url;
        const spec_name = result.spec_name;
        
        let download_html = `
            <div class="alert alert-success">
                <strong>✓ Success!</strong> Your specification document has been generated.
            </div>
            
            <div class="download-buttons mb-4">
        `;
        
        // Add markdown download button
        if (markdown_url) {
            download_html += `
                <a href="${markdown_url}" 
                   class="btn btn-primary btn-lg" 
                   download
                   target="_blank">
                    <svg class="icon icon-sm" style="width: 16px; height: 16px; vertical-align: text-bottom;">
                        <use href="#icon-file-text"></use>
                    </svg>
                    Download Markdown
                </a>
            `;
        }
        
        // Add PDF download button
        if (pdf_url) {
            download_html += `
                <a href="${pdf_url}" 
                   class="btn btn-success btn-lg" 
                   download
                   target="_blank">
                    <svg class="icon icon-sm" style="width: 16px; height: 16px; vertical-align: text-bottom;">
                        <use href="#icon-file"></use>
                    </svg>
                    Download PDF
                </a>
            `;
        }
        
        download_html += `
            </div>
            
            <div class="text-center">
                <a href="/app/project-specification/${spec_name}" 
                   class="btn btn-link" 
                   target="_blank">
                    View in Project Specification →
                </a>
            </div>
        `;
        
        // Hide generate button and show downloads
        this.page_content.find('#btn-generate-spec').hide();
        this.page_content.find('#generation-status').hide();
        this.page_content.find('#download-section').html(download_html).show();
    }

    go_to_step(step) {
        this.page_content.find('.step-content').hide();
        this.page_content.find(`#step-${step}`).show();
        
        this.page_content.find('.step').removeClass('active completed');
        this.page_content.find(`.step[data-step="${step}"]`).addClass('active');
        
        for (let i = 1; i < step; i++) {
            this.page_content.find(`.step[data-step="${i}"]`).addClass('completed');
        }
    }

    show_loading(message) {
        this.page_content.find('#loading-text').html(message);
        this.page_content.find('#loading-overlay').fadeIn(200);
    }

    hide_loading() {
        this.page_content.find('#loading-overlay').fadeOut(200);
    }
}