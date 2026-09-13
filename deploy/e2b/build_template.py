"""Build once, then configure E2B_TEMPLATE with the returned template ID."""
from e2b import Template, default_build_logger

if __name__ == '__main__':
    template = (Template().from_template('opencode')
                .run_cmd('npm install -g opencode-ai@1.16.2', user='root')
                .run_cmd('python3 --version && opencode --version'))
    result = Template.build(template, 'contract-opencode-1-16-2', cpu_count=2,
                            memory_mb=2048, on_build_logs=default_build_logger())
    print(result)
