import os
import sys
import django

current_dir = os.path.dirname(os.path.abspath(__file__))

root_dir = os.path.dirname(current_dir)

sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, 'braincomua_project'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'braincomua_project.settings')

django.setup()