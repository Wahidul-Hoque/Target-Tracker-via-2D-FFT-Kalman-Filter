"""Launch the Django GUI locally. The tracking engine is unchanged."""
import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'webconfig.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line([sys.argv[0], 'runserver', '127.0.0.1:8000', '--noreload'])
