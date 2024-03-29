# Generated by Django 4.0.4 on 2022-05-21 07:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('work', '0003_add_profile_image'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='listing',
            name='profile_image',
        ),
        migrations.AddField(
            model_name='listing',
            name='application_url',
            field=models.URLField(max_length=500, null=True),
        ),
        migrations.AlterField(
            model_name='listing',
            name='profile_url',
            field=models.URLField(max_length=500, null=True),
        ),
    ]
