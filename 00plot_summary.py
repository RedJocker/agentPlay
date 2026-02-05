import matplotlib.pyplot as plt
import numpy as np

# Data from the lead summary report
status_labels = ['New', 'Contacted', 'Qualified', 'Disqualified', 'Won']
status_counts = [1, 1, 1, 1, 1]

# Financial data (all values in USD)
financial_categories = ['Active Pipeline', 'Won Deal']
financial_values = [250000, 75000]  # $50k + $200k active, $75k won

# Project distribution
projects = ['Enterprise CRM Rollout', 'SMB Outreach Campaign', 'International Expansion']
project_counts = [2, 2, 1]

# Manager assignments
managers = ['Alice Johnson', 'Bob Smith', 'Carol Lee', 'Dave Patel']
manager_counts = [2, 2, 1, 1]

# Create figure and subplots
fig, axs = plt.subplots(2, 2, figsize=(12, 10))
fig.suptitle('Lead Management Analysis - Feb 4, 2026', fontsize=16)

# 1. Status Distribution (Pie Chart)
axs[0, 0].pie(status_counts, labels=status_labels, autopct='%1.1f%%', startangle=90,
             colors=plt.cm.Paired.colors)
axs[0, 0].set_title('Lead Status Distribution')

# 2. Financial Overview (Bar Chart)
axs[0, 1].bar(financial_categories, financial_values, color=['#1f77b4', '#2ca02c'])
axs[0, 1].set_title('Financial Overview')
axs[0, 1].set_ylabel('USD')
axs[0, 1].grid(axis='y', linestyle='--', alpha=0.7)
for i, v in enumerate(financial_values):
    axs[0, 1].text(i, v + 5000, f'${v/1000:.0f}k', ha='center')

# 3. Project Distribution (Bar Chart)
axs[1, 0].bar(projects, project_counts, color='#ff7f0e')
axs[1, 0].set_title('Project Distribution')
axs[1, 0].set_xticklabels(projects, rotation=15, ha='right')
for i, v in enumerate(project_counts):
    axs[1, 0].text(i, v + 0.1, str(v), ha='center')

# 4. Manager Assignments (Bar Chart)
axs[1, 1].bar(managers, manager_counts, color='#d62728')
axs[1, 1].set_title('Manager Assignments')
axs[1, 1].set_xticklabels(managers, rotation=25, ha='right')
for i, v in enumerate(manager_counts):
    axs[1, 1].text(i, v + 0.1, str(v), ha='center')

# Adjust layout and save
plt.tight_layout()
plt.subplots_adjust(top=0.9)
plt.savefig('lead_analysis.png', dpi=300, bbox_inches='tight')
plt.show()
plt.close()

print("Lead analysis charts generated and saved as 'lead_analysis.png'")




