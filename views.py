from django.shortcuts import redirect, render, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponseRedirect

from plugins.pandoc_plugin import forms, plugin_settings

from submission import models as sub_models
from core import models as core_models
from production import logic

from utils import setting_handler, models

import os
import subprocess
from bs4 import BeautifulSoup

def index(request):
    '''
    Render admin page allowing users to enable or disable the plugin
    '''
    plugin = models.Plugin.objects.get(name=plugin_settings.SHORT_NAME)
    pandoc_enabled = setting_handler.get_plugin_setting(plugin, 'pandoc_enabled', request.journal, create=True,
                                                        pretty='Enable Pandoc', types='boolean').processed_value
    admin_form = forms.PandocAdminForm(initial={'pandoc_enabled': pandoc_enabled})

    if request.POST:
        admin_form = forms.PandocAdminForm(request.POST)

        if admin_form.is_valid():
            for setting_name, setting_value in admin_form.cleaned_data.items():
                setting_handler.save_plugin_setting(plugin, setting_name, setting_value, request.journal)
                messages.add_message(request, messages.SUCCESS, '{0} setting updated.'.format(setting_name))

            return redirect(reverse('pandoc_index'))

    template = "pandoc_plugin/index.html"
    context = {
        'admin_form': admin_form,
    }

    return render(request, template, context)


def convert(request, article_id=None, file_id=None):
    '''
    If request is POST, try to get article's manuscript file (should be docx or rtf), convert to markdown, then convert to html,
    save new files in applicable locations, register as Galley objects in database. Refresh submission page with new galley objects.
    If request is GET, render button to convert.
    '''

    # Argument added to all calls to pandoc that caps the size of Pandoc's heap,
    # preventing maliciously formatted files from triggering a runaway
    # conversion process.
    memory_limit = ['+RTS', '-M512M', '-RTS']
    base_pandoc_command = ['pandoc'] + memory_limit

    # if post, get the original manuscript file, convert to html
    if request.method == "POST":

        # retrieve article and selected manuscript
        article = get_object_or_404(sub_models.Article, pk=article_id)
        manuscript = get_object_or_404(core_models.File, pk=file_id)

        orig_path = manuscript.self_article_path()

        # generate a filename for the intermediate md file - raise error if unexpected manuscript file type
        stripped_path, exten = os.path.splitext(orig_path)

        if exten not in ['.docx', '.rtf']:
            messages.add_message(request, messages.ERROR, 'The Pandoc plugin currently only supports .docx and .rtf filetypes')
            return HttpResponseRedirect(request.META.get('HTTP_REFERER'))

        if request.POST.get('convert_html'):

            output_path = stripped_path + '.html'

            pandoc_command = base_pandoc_command + ['-s', orig_path, '-t', 'html']

            try:
                pandoc_return = subprocess.run(pandoc_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as e:
                messages.add_message(request, messages.ERROR, 'Pandoc encountered the following error when executing the command {cmd}: {err}'.format(cmd=e.cmd, err=e.stderr))
                return HttpResponseRedirect(request.META.get('HTTP_REFERER'))

            pandoc_soup = BeautifulSoup(pandoc_return.stdout, 'html.parser')

            for img in pandoc_soup.find_all("img"):
                # Pandoc adds `media/` to the src attributes of all the img tags it creates. We want to remove that prefix and leave only the base filename.
                img["src"] = img["src"].replace("media/", "")
                # Pandoc also guesses at the height/width attributes of images. We wish to strip those style tags
                del img["style"]

            # Write revised HTML to file
            with open(output_path, mode="w", encoding="utf-8") as html_file:
                print(pandoc_soup, file=html_file)

            logic.save_galley(article, request, output_path, True, 'HTML', False, save_to_disk=False)

            # TODO: make new file child of manuscript file

        return redirect(reverse('production_article', kwargs={'article_id': article.pk}))

    # render buttons if GET request
    else:
        return reverse('production_article', kwargs={'article_id': request.article.pk})

# NEED LOGIC FOR IF HTML ALREADY GENERATED