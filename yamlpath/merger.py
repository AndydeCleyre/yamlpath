"""
Implement YAML document Merger.

Copyright 2019, 2020 William W. Kimball, Jr. MBA MSIS


=========
DEV NOTES
=========
yaml-merge [OPTIONS] file1 [file... [fileN]]

OPTIONS:
* DEFAULT behaviors when handling:
  * arrays (keep LHS, keep RHS, append uniques, append all [default])
  * hashes (keep LHS, keep RHS, deep merge [default])
  * arrays-of-hashes (requires identifier key; then regular hash options)
  * arrays-of-arrays (regular array options)
* anchor conflict handling (keep LHS, keep RHS, rename per file [aliases in
  same file follow suit], stop merge [default])
* merge-at (a YAML Path which indicates where in the LHS document all RHS
  documents are merged into [default=/])
* output (file)
* Configuration file for per-path options, like:
---
/just/an/array:  first|last|unique|all
/juat/a/hash:  first|last|shallow|deep
some.path.pointing.at.an.array.of.hashes:
  identity: key_with_unique_identifying_values
  merge: deep

Array-of-Arrays:
[[5,6],[1,2],[4,3]]
- - 5
  - 6
- - 1
  - 2
- - 4
  - 3

================================== EXAMPLE ====================================
aliases:
 - &scalar_anchor LHS aliased value
 - &unchanging_anchor Same value everywhere
key: LHS value
hash:
  key1: sub LHS value 1
  key2: sub LHS value 2
  complex:
    subkeyA: *scalar_anchor
array:
  - LHS element 1
  - non-unique element
  - *scalar_anchor
  - *unchanging_anchor

<< (RHS overrides LHS scalars;
    deep Hash merge;
    keep only unique Array elements; and
    rename conflicting anchors)

aliases:
 - &scalar_anchor RHS aliased value
 - &unchanging_anchor Same value everywhere
key: RHS value
hash:
  key1: sub RHS value 1
  key3: sub RHS value 3
  complex:
    subkeyA: *scalar_anchor
    subkeyB:
      - a
      - list
array:
  - RHS element 1
  - non-unique element
  - *scalar_anchor
  - *unchanging_anchor

==

aliases:
 - &scalar_anchor_1 LHS aliased value
 - &scalar_anchor_2 RHS aliased value
 - &unchanging_anchor Same value everywhere
key: RHS value
hash:
  key1: sub RHS value 1
  key2: sub LHS value 2
  key3: sub RHS value 3
  complex:
    subkeyA: *scalar_anchor_2  # Because "RHS overrides LHS scalars"
    subkeyB:
      - a
      - list
array:
  - LHS element 1
  - non-unique element
  - *scalar_anchor_1
  - *unchanging_anchor
  - RHS element 1
  - *scalar_anchor_2
===============================================================================

Processing Requirements:
1. Upon opening a YAML document, immediately scan the entire file for all
   anchor names.  Track those names across all documents as they are opened
   because conflicts must be resolved per user option selection.
2. LHS and RHS anchored maps must have identical names AND anchor names to be
   readily merged.  If only one of them is anchored, a merge is possible; keep
   the only anchor name on the map.  If they have different anchor names, treat
   as an anchor conflict and resolve per user option setting.
"""
from typing import Any

import ruamel.yaml
from ruamel.yaml.scalarstring import ScalarString

from yamlpath.wrappers import ConsolePrinter, NodeCoords
from yamlpath.enums import (
    AnchorConflictResolutions,
    AoHMergeOpts,
    ArrayMergeOpts,
    HashMergeOpts,
    PathSeperators
)
from yamlpath.func import append_list_element, escape_path_section
from yamlpath import Processor, MergerConfig


class Merger:
    """Performs YAML document merges."""

    def __init__(
            self, logger: ConsolePrinter, lhs: Any, config: MergerConfig
    ) -> None:
        """
        Instantiate this class into an object.

        Parameters:
        1. logger (ConsolePrinter) Instance of ConsoleWriter or subclass
        2. args (dict) Default options for merge rules
        3. lhs (Any) The prime left-hand-side parsed YAML data
        4. config (Processor) Processor-wrapped user-defined YAML Paths
            providing precise document merging rules

        Returns:  N/A

        Raises:  N/A
        """
        self.logger: ConsolePrinter = logger
        self.data: Any = lhs
        self.config: Processor = config

    def _merge_dicts(
        self, lhs: dict, rhs: dict,
        parent: Any = None, parentref: Any = None,
        path: str = ""
    ) -> dict:
        """Merges two YAML maps (dicts)."""
        node_coord = NodeCoords(rhs, parent, parentref)
        self.logger.debug(
            "Merger::_merge_dicts:  Evaluating dict at '{}'."
            .format(path))

        # lhs_is_dict = isinstance(lhs, dict)
        # rhs_is_dict = isinstance(rhs, dict)
        # if not rhs_is_dict:
        #     self.logger.error("The RHS data is not a Hash.", 30)
        # if not lhs_is_dict:
        #     self.logger.error("The LHS data is not a Hash.", 30)
        # if (rhs_is_dict and not lhs_is_dict) or (
        #         lhs_is_dict and not rhs_is_dict):
        #     self.logger.error("Incompatible data-types found at {}."
        #               .format(path), 30)

        # The document root is ALWAYS a Hash.  For everything deeper, do not
        # merge when the user sets LEFT|RIGHT Hash merge options.
        if len(path) > 0:
            merge_mode = self.config.hash_merge_mode(node_coord)
            if merge_mode is HashMergeOpts.LEFT:
                return lhs
            if merge_mode is HashMergeOpts.RIGHT:
                return rhs

        # Deep merge
        buffer = []
        buffer_pos = 0
        for key, val in rhs.items():
            path_next = path + "/" + str(key).replace("/", "\\/")
            self.logger.debug(
                "Merger::_merge_dicts:  Processing key {}{} at '{}'."
                .format(key, type(key), path_next))
            if key in lhs:
                # Write the buffer if populated
                for b_key, b_val in buffer:
                    lhs.insert(buffer_pos, b_key, b_val)
                buffer = []

                # LHS has the RHS key
                if isinstance(val, dict):
                    lhs[key] = self._merge_dicts(
                        lhs[key], val, rhs, key, path_next)
                elif isinstance(val, list):
                    lhs[key] = self._merge_lists(
                        lhs[key], val, rhs, key, path_next)
                else:
                    lhs[key] = val
            else:
                # LHS lacks the RHS key.  Buffer this key-value pair in order
                # to insert it ahead of whatever key(s) follow this one in RHS
                # to keep anchor definitions before their aliases.
                buffer.append((key, val))

            buffer_pos += 1

        # Write any remaining buffered content to the end of LHS
        for b_key, b_val in buffer:
            lhs[b_key] = b_val

        return lhs

    def _merge_simple_lists(
        self, lhs: list, rhs: list,
        node_coord: NodeCoords, path: str = ""
    ) -> list:
        """Merge two lists of Scalars or lists."""
        merge_mode = self.config.array_merge_mode(node_coord)
        if merge_mode is ArrayMergeOpts.LEFT:
            return lhs
        if merge_mode is ArrayMergeOpts.RIGHT:
            return rhs

        append_all = merge_mode is ArrayMergeOpts.ALL
        for idx, ele in enumerate(rhs):
            path_next = path + "[{}]".format(idx)
            self.logger.debug(
                "Merger::_merge_simple_lists:  Processing element {}{} at {}."
                .format(ele, type(ele), path_next))

            if append_all or (ele not in lhs):
                append_list_element(
                    lhs, ele,
                    ele.anchor.value if hasattr(ele, "anchor") else None)
        return lhs

    def _merge_arrays_of_hashes(
        self, lhs: list, rhs: list,
        node_coord: NodeCoords, path: str = ""
    ) -> list:
        """Merge two lists of dicts (Arrays-of-Hashes)."""
        merge_mode = self.config.aoh_merge_mode(node_coord)
        if merge_mode is AoHMergeOpts.LEFT:
            return lhs
        if merge_mode is AoHMergeOpts.RIGHT:
            return rhs

        for idx, ele in enumerate(rhs):
            path_next = path + "[{}]".format(idx)
            node_next = NodeCoords(ele, rhs, idx)
            self.logger.debug(
                "Merger::_merge_arrays_of_hashes:  Processing element {}{}\
                 at {}."
                .format(ele, type(ele), path_next))

            if merge_mode is AoHMergeOpts.DEEP:
                id_key = self.config.aoh_merge_key(node_next, ele)
                rhs_key_value = ele[id_key]
                merged_hash = False
                for lhs_hash in lhs:
                    if id_key in lhs_hash \
                            and lhs_hash[id_key] == rhs_key_value:
                        lhs_hash = self._merge_dicts(
                            lhs_hash, ele, rhs, idx, path_next)
                        merged_hash = True
                        break
                if not merged_hash:
                    append_list_element(lhs, ele,
                        ele.anchor.value if hasattr(ele, "anchor") else None)
            elif merge_mode is AoHMergeOpts.UNIQUE:
                if ele not in lhs:
                    append_list_element(
                        lhs, ele,
                        ele.anchor.value if hasattr(ele, "anchor") else None)
            else:
                append_list_element(lhs, ele,
                    ele.anchor.value if hasattr(ele, "anchor") else None)
        return lhs

    def _merge_lists(
        self, lhs: list, rhs: list,
        parent: Any = None, parentref: Any = None,
        path: str = ""
    ) -> list:
        """Merge two lists."""
        node_coord = NodeCoords(rhs, parent, parentref)
        if len(rhs) > 0:
            if isinstance(rhs[0], dict):
                # This list is an Array-of-Hashes
                return self._merge_arrays_of_hashes(lhs, rhs, node_coord, path)

            # This list is an Array-of-Arrays or a simple list of Scalars
            return self._merge_simple_lists(lhs, rhs, node_coord, path)

        # No RHS list
        return lhs

    def _calc_unique_anchor(self, anchor: str, known_anchors: dict):
        """Generate a unique anchor name within a document pair."""
        self.logger.debug("Merger::_calc_unique_anchor:  Preexisting Anchors:")
        self.logger.debug(known_anchors)
        while anchor in known_anchors:
            anchor = "{}_{}".format(
                anchor,
                str(hash(anchor)).replace("-", "_"))
            self.logger.debug(
                "Merger::_calc_unique_anchor:  Trying new anchor name, {}."
                .format(anchor))
        return anchor

    def _resolve_anchor_conflicts(self, rhs):
        """Resolve anchor conflicts."""
        lhs_anchors = {}
        Merger.scan_for_anchors(self.data, lhs_anchors)
        self.logger.debug("Merger::_resolve_anchor_conflicts:  LHS Anchors:")
        self.logger.debug(lhs_anchors)

        rhs_anchors = {}
        Merger.scan_for_anchors(rhs, rhs_anchors)
        self.logger.debug("Merger::_resolve_anchor_conflicts:  RHS Anchors:")
        self.logger.debug(rhs_anchors)

        for anchor in [anchor
                for anchor in rhs_anchors
                if anchor in lhs_anchors
        ]:
            # It is only a conflict if the value differs; however, the
            # value may be a scalar, list, or dict.  Further, lists and
            # dicts may contain other aliased values which must also be
            # checked for equality (or pointing at identical anchors).
            prime_alias = lhs_anchors[anchor]
            reader_alias = rhs_anchors[anchor]
            conflict_mode = self.config.anchor_merge_mode()

            if isinstance(prime_alias, dict):
                self.logger.error(
                    "Dictionary-based anchor conflict resolution is not yet"
                    " implemented.", 142)
            elif isinstance(prime_alias, list):
                self.logger.error(
                    "List-based anchor conflict resolution is not yet"
                    " implemented.", 142)
            else:
                if prime_alias != reader_alias:
                    if conflict_mode is AnchorConflictResolutions.RENAME:
                        self.logger.debug(
                            "Anchor {} conflict; will RENAME anchors."
                            .format(anchor))
                        Merger.rename_anchor(
                            rhs, anchor,
                            self._calc_unique_anchor(
                                anchor,
                                set(lhs_anchors.keys())
                                .union(set(rhs_anchors.keys()))
                            )
                        )
                    elif conflict_mode is AnchorConflictResolutions.LEFT:
                        self.logger.debug(
                            "Anchor {} conflict; LEFT will override."
                            .format(anchor))
                        self._overwrite_aliased_values(self.data, rhs, anchor)
                    elif conflict_mode is AnchorConflictResolutions.RIGHT:
                        self.logger.debug(
                            "Anchor {} conflict; RIGHT will override."
                            .format(anchor))
                        self._overwrite_aliased_values(rhs, self.data, anchor)
                    else:
                        self.logger.error(
                            "Aborting due to anchor conflict, {}"
                            .format(anchor), 4)

    def _overwrite_aliased_values(
        self, source_dom: Any, target_dom: Any, anchor: str
    ) -> None:
        """Replace the value of every alias of an anchor."""
        def recursive_anchor_replace(
            data: Any, anchor_val: str, repl_node: Any
        ):
            if isinstance(data, dict):
                for idx, key in [
                    (idx, key) for idx, key in enumerate(data.keys())
                    if hasattr(key, "anchor")
                        and key.anchor.value == anchor_val
                ]:
                    data.insert(idx, repl_node, data.pop(key))

                for key, val in data.non_merged_items():
                    if (hasattr(val, "anchor")
                            and val.anchor.value == anchor_val):
                        data[key] = repl_node
                    else:
                        recursive_anchor_replace(
                            val, anchor_val, repl_node)
            elif isinstance(data, list):
                for idx, ele in enumerate(data):
                    if (hasattr(ele, "anchor")
                            and ele.anchor.value == anchor_val):
                        data[idx] = repl_node
                    else:
                        recursive_anchor_replace(ele, anchor_val, repl_node)

        # Python will treat the source and target anchors as distinct even
        # after if their string names are identical.  This will cause the
        # resulting YAML to have duplicate anchor definitions, which is illegal
        # and would produce illegible output.  In order for Python to treat all
        # of the post-synchronized aliases as copies of each other -- and thus
        # produce a useful, de-duplicated YAML output -- a reference to the
        # source anchor node must be copied over the target nodes.  To do so, a
        # Path to at least one alias in the source document must be known.
        # With it, retrieve one of the source nodes and use it to recursively
        # overwrite every occurence of the same anchor within the target DOM.
        source_path = Merger.search_for_anchor(source_dom, anchor)
        source_proc = Processor(self.logger, source_dom)
        source_node = None
        for node_coord in source_proc.get_nodes(source_path, mustexist=True):
            source_node = node_coord.node
            break

        recursive_anchor_replace(target_dom, anchor, source_node)

    def merge_with(self, rhs: Any) -> None:
        """Merge this document with another."""
        # Remove all comments (no sensible way to merge them)
        Merger.delete_all_comments(rhs)

        # Resolve any anchor conflicts
        self._resolve_anchor_conflicts(rhs)

        # Prepare the merge rules
        self.config.prepare(rhs)

        # Loop through all elements in RHS
        if isinstance(rhs, dict):
            # The document root is a map
            self.data = self._merge_dicts(self.data, rhs)
        elif isinstance(rhs, list):
            # The document root is a list
            self.data = self._merge_lists(self.data, rhs)

    @classmethod
    def scan_for_anchors(cls, dom: Any, anchors: dict):
        """Scan a document for all anchors contained within."""
        if isinstance(dom, dict):
            for key, val in dom.items():
                if hasattr(key, "anchor") and key.anchor.value is not None:
                    anchors[key.anchor.value] = key

                if hasattr(val, "anchor") and val.anchor.value is not None:
                    anchors[val.anchor.value] = val

                # Recurse into complex values
                if isinstance(val, (dict, list)):
                    Merger.scan_for_anchors(val, anchors)

        elif isinstance(dom, list):
            for ele in dom:
                Merger.scan_for_anchors(ele, anchors)

        elif hasattr(dom, "anchor"):
            anchors[dom.anchor.value] = dom

    @classmethod
    def search_for_anchor(cls, dom: Any, anchor: str, path: str = "") -> str:
        """Returns the YAML Path to the first appearance of an Anchor."""
        if isinstance(dom, dict):
            for key, val in dom.items():
                path_next = path + "/{}".format(
                    escape_path_section(str(key), PathSeperators.FSLASH))
                if hasattr(key, "anchor") and key.anchor.value == anchor:
                    return path + "/&{}".format(anchor)
                if hasattr(val, "anchor") and val.anchor.value == anchor:
                    return path_next
                return Merger.search_for_anchor(val, anchor, path_next)
        elif isinstance(dom, list):
            for idx, ele in enumerate(dom):
                path_next = path + "[{}]".format(idx)
                return Merger.search_for_anchor(ele, anchor, path_next)
        elif hasattr(dom, "anchor") and dom.anchor.value == anchor:
            return path

        return None

    @classmethod
    def rename_anchor(cls, dom: Any, anchor: str, new_anchor: str):
        """Rename every use of an anchor in a document."""
        if isinstance(dom, dict):
            for key, val in dom.items():
                if hasattr(key, "anchor") and key.anchor.value == anchor:
                    key.anchor.value = new_anchor
                if hasattr(val, "anchor") and val.anchor.value == anchor:
                    val.anchor.value = new_anchor
                Merger.rename_anchor(val, anchor, new_anchor)
        elif isinstance(dom, list):
            for ele in dom:
                Merger.rename_anchor(ele, anchor, new_anchor)
        elif hasattr(dom, "anchor") and dom.anchor.value == anchor:
            dom.anchor.value = new_anchor

    # pylint: disable=line-too-long
    @classmethod
    def delete_all_comments(cls, dom: Any) -> None:
        """
        Recursively delete all comments from a YAML document.

        See:  https://stackoverflow.com/questions/60080325/how-to-delete-all-comments-in-ruamel-yaml/60099750#60099750
        """
        if isinstance(dom, dict):
            for key, val in dom.items():
                Merger.delete_all_comments(key)
                Merger.delete_all_comments(val)
        elif isinstance(dom, list):
            for ele in dom:
                Merger.delete_all_comments(ele)
        try:
            # literal scalarstring might have comment associated with them
            attr = "comment" if isinstance(dom, ScalarString) \
                else ruamel.yaml.comments.Comment.attrib
            delattr(dom, attr)
        except AttributeError:
            pass
