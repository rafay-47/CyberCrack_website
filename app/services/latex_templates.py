"""
Professional LaTeX Resume Template

This file contains the enhanced LaTeX template for generating professional, ATS-friendly resumes.
"""

from string import Template

RESUME_LATEX_TEMPLATE = Template("""\\documentclass[a4paper,11pt]{article}
\\usepackage[margin=0.55in]{geometry}
\\usepackage{titlesec}
\\usepackage{enumitem}
\\usepackage{xcolor}
\\usepackage{hyperref}
\\usepackage{array}

% Define professional color scheme
\\definecolor{primary}{RGB}{0, 0, 102}
\\definecolor{secondary}{RGB}{64, 64, 64}
\\definecolor{accent}{RGB}{0, 102, 204}

% Hyperlink setup
\\hypersetup{
    colorlinks=true,
    linkcolor=primary,
    urlcolor=primary,
    pdfborder={0 0 0}
}

% Section formatting - professional with underlines
\\titleformat{\\section}
{\\bfseries\\color{primary}\\normalsize}
{}{0pt}
{}
[{\\titlerule[0.8pt]}]
\\titlespacing*{\\section}{0pt}{14pt}{6pt}

% Remove page numbering
\\pagenumbering{gobble}

% Itemize formatting - clean and professional
\\setlist[itemize]{leftmargin=15pt, itemsep=1pt, parsep=0pt, topsep=2pt, partopsep=0pt}

% Custom commands for consistent formatting
\\newcommand{\\resumeSubheading}[4]{
  \\vspace{-1pt}\\item
    \\begin{tabular*}{0.97\\textwidth}[t]{l@{\\extracolsep{\\fill}}r}
      \\textbf{#1} & #2 \\\\
      \\textit{\\small#3} & \\textit{\\small #4} \\\\
    \\end{tabular*}\\vspace{-5pt}
}

\\newcommand{\\resumeItem}[1]{
  \\item\\small{
    {#1 \\vspace{-2pt}}
  }
}

\\newcommand{\\resumeSubItem}[1]{\\resumeItem{#1}\\vspace{-4pt}}

\\begin{document}

% Header Section - Professional and Clean
\\begin{center}
    {\\LARGE \\textbf{$name}}\\\\[3pt]
    \\small $headline \\\\[6pt]
    \\begin{tabular}{rcr}
        \\textbf{$phone}
        & \\href{mailto:$email}{$email}
        & \\textbf{$location} \\\\
    \\end{tabular}\\\\[3pt]
    $links_section
\\end{center}

$sections

\\end{document}
""")

HEADER_LINKS_TEMPLATE = """{links}"""

PROFESSIONAL_SUMMARY_TEMPLATE = """\\section{{Professional Summary}}
\\small
{summary}
\\vspace{{8pt}}
"""

EXPERIENCE_TEMPLATE = """\\section{{Experience}}
\\small
{experience_items}"""

EXPERIENCE_ITEM_TEMPLATE = """\\noindent\\textbf{{{title}}}, {company} \\hfill \\textbf{{{date_range}}}
\\begin{{itemize}}
{bullet_points}\\end{{itemize}}
\\vspace{{4pt}}

"""

TECHNICAL_SKILLS_TEMPLATE = """\\section{{Technical Skills}}
\\begin{{itemize}}
{skills_items}\\end{{itemize}}
\\vspace{{4pt}}
"""

SKILLS_ITEM_TEMPLATE = """\\item \\textbf{{{category}:}} {skills}
"""

PROJECTS_TEMPLATE = """\\section{{Projects}}
\\small
{project_items}"""

PROJECT_ITEM_TEMPLATE = """\\noindent\\textbf{{{title}}} {tech_stack}
\\begin{{itemize}}
{bullet_points}\\end{{itemize}}
\\vspace{{3pt}}

"""

CERTIFICATIONS_TEMPLATE = """\\section{{Online Courses \\& Certifications}}
\\small
\\begin{{itemize}}
{certification_items}\\end{{itemize}}
\\vspace{{4pt}}
"""

CERTIFICATION_ITEM_TEMPLATE = """\\item {name} ({date}) 
\\href{{{link}}}{{{issuer}}}"""

EDUCATION_TEMPLATE = """\\section{{Education}}
\\small
{education_items}\\vspace{{4pt}}
"""

EDUCATION_ITEM_TEMPLATE = """\\noindent\\textbf{{{school}}} \\hfill \\textbf{{{date_range}}}\\\\
{degree}
\\vspace{{3pt}}

"""