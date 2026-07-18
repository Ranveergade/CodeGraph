import os
import shutil
import tempfile
import traceback
import zipfile

from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from .models import Scan
from .services.code_scanner import scan_project

SAMPLE_PROJECT_DIR = os.path.join(settings.BASE_DIR, 'sample_project')


def index(request):
    recent_scans = Scan.objects.all()[:8]
    return render(request, 'analyzer/index.html', {'recent_scans': recent_scans})


def _safe_extract(zip_path, dest_dir):
    """Extract a zip file while guarding against path-traversal ('zip slip')."""
    dest_dir = os.path.normpath(dest_dir)
    with zipfile.ZipFile(zip_path) as zf:
        safe_members = []
        for member in zf.namelist():
            member_path = os.path.normpath(os.path.join(dest_dir, member))
            if member_path == dest_dir or member_path.startswith(dest_dir + os.sep):
                safe_members.append(member)
        zf.extractall(dest_dir, members=safe_members)


def _find_effective_root(extracted_dir):
    """
    If the zip contains a single top-level folder (common when zipping a
    project directory), scan inside that folder instead of the wrapper.
    """
    entries = [e for e in os.listdir(extracted_dir) if not e.startswith('__MACOSX')]
    if len(entries) == 1:
        candidate = os.path.join(extracted_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate
    return extracted_dir


def analyze(request):
    if request.method != 'POST':
        return redirect('analyzer:index')

    source = request.POST.get('source')
    tmp_dir = None

    try:
        if source == 'sample':
            root_path = SAMPLE_PROJECT_DIR
            label = 'sample_project'
            name = 'Sample Django Project'
        elif source == 'upload':
            uploaded = request.FILES.get('project_zip')
            if not uploaded:
                messages.error(request, 'Please choose a .zip file to upload.')
                return redirect('analyzer:index')
            if not uploaded.name.lower().endswith('.zip'):
                messages.error(request, 'Only .zip files are supported.')
                return redirect('analyzer:index')

            tmp_dir = tempfile.mkdtemp(prefix='codegraph_')
            zip_path = os.path.join(tmp_dir, uploaded.name)
            with open(zip_path, 'wb') as f:
                for chunk in uploaded.chunks():
                    f.write(chunk)

            extract_dir = os.path.join(tmp_dir, 'extracted')
            os.makedirs(extract_dir, exist_ok=True)
            _safe_extract(zip_path, extract_dir)
            root_path = _find_effective_root(extract_dir)
            label = uploaded.name
            name = uploaded.name.rsplit('.', 1)[0]
        else:
            messages.error(request, 'Unknown analysis source.')
            return redirect('analyzer:index')

        has_py_files = any(
            f.endswith('.py')
            for _, _, files in os.walk(root_path)
            for f in files
        )
        if not has_py_files:
            messages.error(request, 'No .py files were found in that project — check the zip contains your source code, not just assets.')
            return redirect('analyzer:index')

        try:
            result = scan_project(root_path)
        except Exception:
            tb = traceback.format_exc()
            return render(request, 'analyzer/scan_error.html', {'traceback': tb, 'name': name}, status=200)

        stats = result['stats']

        scan = Scan.objects.create(
            name=name,
            source_label=label,
            total_files=stats['total_files'],
            total_nodes=stats['total_nodes'],
            total_edges=stats['total_edges'],
            dead_code_count=stats['dead_code_count'],
            cycle_count=stats['cycle_count'],
            result_json=result,
        )
        return redirect('analyzer:graph_detail', pk=scan.pk)

    finally:
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def graph_detail(request, pk):
    scan = get_object_or_404(Scan, pk=pk)
    return render(request, 'analyzer/graph.html', {'scan': scan})


def history(request):
    scans = Scan.objects.all()
    return render(request, 'analyzer/index.html', {'recent_scans': scans, 'show_all': True})


def delete_scan(request, pk):
    scan = get_object_or_404(Scan, pk=pk)
    if request.method == 'POST':
        scan.delete()
        messages.success(request, 'Scan deleted.')
    return redirect('analyzer:index')
