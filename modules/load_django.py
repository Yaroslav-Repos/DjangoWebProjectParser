import sys
import os
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'braincomua_project')))

os.environ['DJANGO_SETTINGS_MODULE'] = 'braincomua_project.settings'

django.setup()