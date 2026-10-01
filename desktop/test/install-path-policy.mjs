import path from 'node:path';

// dpkg -L includes existing shared ancestors such as /usr/share. The package
// neither owns nor sets those directories' permissions. Check every installed
// file, and directories belonging to the actual application installation tree.
export function requiresProtectedPermissions(entry, isDirectory, applicationRoot, isSymbolicLink = false) {
  if (!isDirectory || isSymbolicLink) return true;
  const relative = path.relative(applicationRoot, entry);
  return relative === '' || (relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}
