from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Scan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='Untitled Project', max_length=255)),
                ('source_label', models.CharField(help_text="Either 'sample_project' or the uploaded zip filename", max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('total_files', models.IntegerField(default=0)),
                ('total_nodes', models.IntegerField(default=0)),
                ('total_edges', models.IntegerField(default=0)),
                ('dead_code_count', models.IntegerField(default=0)),
                ('cycle_count', models.IntegerField(default=0)),
                ('result_json', models.JSONField(default=dict)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
