############################################################################
# Copyright (c) 2020 Saint Petersburg State University
# # All Rights Reserved
# See file LICENSE for details.
############################################################################

import logging
from Bio import SeqIO

from src.common import *
from src.long_read_assigner import *


logger = logging.getLogger('IsoQuant')


class PrintAllFunctor:
    def check(self, assignment):
        return True


class PrintOnlyFunctor:
    def __init__(self, allowed_types):
        if isinstance(allowed_types, list):
            self.allowed_types = set(allowed_types)
        elif isinstance(allowed_types, set):
            self.allowed_types = allowed_types
        else:
            self.allowed_types = {allowed_types}

    def check(self, assignment):
        if assignment is None:
            return False
        return assignment.assignment_type in self.allowed_types


class AbstractAssignmentPrinter:
    def __init__(self, output_file_name, params, assignment_checker=PrintAllFunctor()):
        self.assignment_checker = assignment_checker
        self.params = params
        self.output_file = open(output_file_name, "w")

    def __del__(self):
        self.output_file.close()

    def add_read_info(self, read_assignment):
        raise NotImplementedError()

    def flush(self):
        self.output_file.flush()


class ReadAssignmentCompositePrinter:
    def __init__(self, printers):
        self.printers = printers

    def add_read_info(self, read_assignment):
        for p in self.printers:
            p.add_read_info(read_assignment)

    def flush(self):
        for p in self.printers:
            p.flush()


# write mapped reads to bed file
class BEDPrinter(AbstractAssignmentPrinter):
    def __init__(self, output_file_name, params, assignment_checker=PrintAllFunctor()):
        AbstractAssignmentPrinter.__init__(self, output_file_name, params, assignment_checker)
        self.output_file.write("#chrom\tchromStart\tchromEnd\tname\tscore\tstrand\tblockCount\tblockSizes\tblockStarts\n")

    def add_read_info(self, read_assignment):
        if read_assignment is None or read_assignment.assignment_type is None or \
                not hasattr(read_assignment, "gene_info") or read_assignment.gene_info is None:
            return
        if self.assignment_checker is None or not self.assignment_checker.check(read_assignment):
            return

        strands = set()
        for isoform_match in read_assignment.isoform_matches:
            isoform_id = isoform_match.assigned_transcript
            if read_assignment.gene_info is not None and isoform_id is not None:
                strands.add(read_assignment.gene_info.isoform_strands[isoform_id])
        if len(strands) != 1:
            strand = read_assignment.mapped_strand
        else:
            strand = list(strands)[0]
        chr_id = read_assignment.gene_info.chr_id
        exon_blocks = read_assignment.combined_profile.read_exon_profile.read_features

        self.output_file.write("%s\t%d\t%d\t%s\t0\t%s\t%d\t%s\t%s\n" %
                           (chr_id, exon_blocks[0][0] - 1, exon_blocks[-1][1],
                            read_assignment.read_id, strand, len(exon_blocks),
                            ",".join([str(e[1] - e[0] + 1) for e in exon_blocks]),
                            ",".join([str(e[0] - 1) for e in exon_blocks])))


class BasicTSVAssignmentPrinter(AbstractAssignmentPrinter):
    def __init__(self, output_file_name, params):
        AbstractAssignmentPrinter.__init__(self, output_file_name, params)
        self.header = "#read_id\tisoform_id\tassignment_type\tassignment_events\tpolyA_found"
        if self.params.cage is not None:
            self.header += "\tCAGE_peak_found"
        if self.params.print_additional_info:
            self.header += "\taligned_blocks\tintron_profile\tsplit_exon_profile"
        self.header += "\n"
        self.output_file.write(self.header)

    def add_read_info(self, read_assignment):
        if read_assignment is None:
            return
        if self.assignment_checker is None or not self.assignment_checker.check(read_assignment):
            return
        if read_assignment.assignment_type is None or read_assignment.isoform_matches is None:
            line = read_assignment.read_id + "\t.\t.\t."
        else:
            assigned_transcripts = [str(m.assigned_transcript) for m in read_assignment.isoform_matches]
            for m in read_assignment.isoform_matches:
                for x in m.match_subclassifications:
                    if not hasattr(x, "event_type"):
                        logger.debug(x)
            match_events = ",".join(["+".join([x.event_type.name for x in m.match_subclassifications])
                                     for m in read_assignment.isoform_matches])
            if not match_events:
                match_events = "."
            line = read_assignment.read_id + "\t" + ",".join(assigned_transcripts) + "\t" \
                + read_assignment.assignment_type.name + "\t" + match_events + "\t" + str(read_assignment.polyA_found)
            if self.params.cage is not None:
                line += '\t' + str(read_assignment.cage_found)
        if self.params.print_additional_info:
            combined_read_profile = read_assignment.combined_profile
            if combined_read_profile is None:
                line += "\t.\t.\t."
            else:
                line += "\t" + range_list_to_str(combined_read_profile.read_split_exon_profile.read_features) + "\t" + \
                    list_to_str(combined_read_profile.read_intron_profile.gene_profile) + "\t" + \
                        list_to_str(combined_read_profile.read_split_exon_profile.gene_profile)
        line += "\n"
        self.output_file.write(line)

    """ sqanti output
    
    isoform: the isoform ID. Usually in PB.X.Y format.
    chrom: chromosome.
    strand: strand.
    length: isoform length.
    exons: number of exons.
    structural_category: one of the categories ["full-splice_match", "incomplete-splice_match", "novel_in_catalog", "novel_not_in_catalog", "genic", "antisense", "fusion", "intergenic", "genic_intron"]
    associated_gene: the reference gene name.
    associated_transcript: the reference transcript name.
    ref_length: reference transcript length.
    ref_exons: reference transcript number of exons.
    diff_to_TSS: distance of query isoform 5' start to reference transcript start end. Negative value means query starts downstream of reference.
    diff_to_TTS: distance of query isoform 3' end to reference annotated end site. Negative value means query ends upstream of reference.
    diff_to_gene_TSS: distance of query isoform 5' start to the closest start end of any transcripts of the matching gene. This field is different from diff_to_TSS since it's looking at all annotated starts of a gene. Negative value means query starts downstream of reference.
    diff_to_gene_TTS: distance of query isoform 3' end to the closest end of any transcripts of the matching gene. Negative value means query ends upstream of reference.
    subcategory: additional splicing categorization, separated by semi-colons. Categories include: mono-exon, multi-exon. Intron rentention is marked with intron_retention.
    RTS_stage: TRUE if one of the junctions could be a RT switching artifact.
    all_canonical: TRUE if all junctions have canonical splice sites.
    - min_sample_cov: sample with minimum coverage.
    - min_cov: minimum junction coverage based on short read STAR junction output file. NA if no short read given.
    - min_cov_pos: the junction that had the fewest coverage. NA if no short read data given.
    - sd_cov: standard deviation of junction coverage counts from short read data. NA if no short read data given.
    - FL or FL.<sample>: FL count associated with this isoform per sample if --fl_count is provided, otherwise NA.
    n_indels: total number of indels based on alignment.
    n_indels_junc: number of junctions in this isoform that have alignment indels near the junction site (indicating potentially unreliable junctions).
    bite: TRUE if all junctions match reference junctions completely.
    - iso_exp: short read expression for this isoform if --expression is provided, otherwise NA.
    - gene_exp: short read expression for the gene associated with this isoform (summing over all isoforms) if --expression is provided, otherwise NA.
    - ratio_exp: ratio of iso_exp to gene_exp if --expression is provided, otherwise NA.
    - FSM_class: ignore this field for now.
    - ORF_length: predicted ORF length.
    - CDS_length: predicted CDS length.
    - CDS_start: CDS start.
    - CDS_end: CDS end.
    CDS_genomic_start: genomic coordinate of the CDS start. If on - strand, this coord will be greater than the end.
    CDS_genomic_end: genomic coordinate of the CDS end. If on - strand, this coord will be smaller than the start.
    - predicted_NMD: TRUE if there's a predicted ORF and CDS ends before the last junction; FALSE if otherwise. NA if non-coding.
    perc_A_downstreamTTS: percent of genomic "A"s in the downstream 20 bp window. If this number if high (say > 0.8), the 3' end site of this isoform is probably not reliable.
    seq_A_downstream_TTS: sequence of the downstream 20 bp window.
    dist_to_cage_peak: distance to closest TSS based on CAGE Peak data. Negative means upstream of TSS and positive means downstream of TSS. Strand-specific. SQANTI2 only searches for nearby CAGE Peaks within 10000 bp of the PacBio transcript start site. Will be NA if none are found within 10000 bp.
    within_cage_peak: TRUE if the PacBio transcript start site is within a CAGE Peak.
    dist_to_polya_site: distance to closest polyA site based on PolyA site data. Negative means upstream of closest site and positive means downstream of closest site. Strand-specific. SQANTI2 only searches for nearby CAGE Peaks within 100 bp of the PacBio transcript start site. Will be NA if none are found within 100 bp.
    within_polya_site: TRUE if the PacBio transcript polyA site is within 100 bp (upstream or downstream) of an annotated polyA site.
    polyA_motif: if --polyA_motif_list is given, shows the top ranking polyA motif found within 50 bp upstream of end.
    polyA_dist: if --polyA_motif_list is given, shows the location of the last base of the hexamer. Position 0 is the putative poly(A) site. This distance is hence always negative because it is upstream.
    
    """


class SqantiTSVPrinter(AbstractAssignmentPrinter):
    def __init__(self, output_file_name, params):
        AbstractAssignmentPrinter.__init__(self, output_file_name, params)
        self.header = 'isoform\tchrom\tstrand\tlength\texons\tstructural_category' \
                      '\tassociated_gene\tassociated_transcript\tref_length\tref_exons\tdiff_to_TSS\tdiff_to_TTS' \
                      '\tdiff_to_gene_TSS\tdiff_to_gene_TTS\tsubcategory\tall_canonical' \
                      '\tn_indels\tn_indels_junc\tbite\tCDS_genomic_start' \
                      '\tCDS_genomic_end\tperc_A_downstreamTTS\tseq_A_downstream_TTS\tdist_to_cage_peak' \
                      '\twithin_cage_peak\tdist_to_polya_site\twithin_polya_site\tpolyA_motif\tpolyA_dist\n'
        self.output_file.write(self.header)
        self.io_support = IOSupport(self.params)

    def add_read_info(self, read_assignment):
        if read_assignment is None:
            return
        # FIXME ambiguous matches
        if read_assignment.assignment_type in [ReadAssignmentType.empty, ReadAssignmentType.ambiguous]:
            return

        gene_info = read_assignment.gene_info
        match = read_assignment.isoform_matches[0]
        gene_id = match.assigned_gene
        transcript_id = match.assigned_transcript
        if transcript_id is None:
            return
        strand = gene_info.isoform_strands[transcript_id]

        # FIXME not genomic distance
        dist_to_tss = self.io_support.count_tss_dist(read_assignment, transcript_id)
        dist_to_tts = self.io_support.count_tts_dist(read_assignment, transcript_id)
        dist_to_gene_tss, dist_to_gene_tts = self.io_support.find_closests_tsts(read_assignment)
        if strand == '-':
            # swapping distances since 5' and 3' are now opposite
            dist_to_tss, dist_to_tts = dist_to_tts, dist_to_tss
            dist_to_gene_tss, dist_to_gene_tts = dist_to_gene_tts, dist_to_gene_tss

        subtypes = ";".join([x.event_type.name for x in match.match_subclassifications])
        if not subtypes:
            subtypes = "."

        indel_count = read_assignment.additional_info["indel_count"] \
            if "indel_count" in read_assignment.additional_info.keys() else "-1"
        junctions_with_indels = read_assignment.additional_info["junctions_with_indels"] \
            if "junctions_with_indels" in read_assignment.additional_info.keys() else "-1"
        bite = self.io_support.check_all_sites_match_reference(read_assignment)
        ref_cds_start, ref_cds_end = self.io_support.find_ref_CDS_region(gene_info, transcript_id)

        if hasattr(gene_info, 'reference_region') and gene_info.reference_region is not None:
            read_introns = read_assignment.combined_profile.read_intron_profile.read_features
            all_canonical = str(self.io_support.check_sites_are_canonical(read_introns, gene_info, strand))
            seq_A_downstream_TTS, perc_A_downstreamTTS = \
                self.io_support.check_downstream_polya((read_assignment.start(), read_assignment.end()), gene_info, strand)
            perc_A_downstreamTTS = "%0.2f" % perc_A_downstreamTTS
        else:
            all_canonical = "NA"
            perc_A_downstreamTTS = "NA"
            seq_A_downstream_TTS = "NA"

        # TODO
        dist_to_cage_peak = "NA"
        within_cage_peak = "NA"
        dist_to_polya_site = "NA"
        within_polya_site = "NA"
        polyA_motif = "NA"
        polyA_dist = "NA"

        l = "\t".join([str(x) for x in [read_assignment.read_id, gene_info.chr_id, strand,
                                        read_assignment.length(), read_assignment.exon_count(),
                                        match.match_classification.name, gene_id, transcript_id,
                                        gene_info.total_transcript_length(transcript_id),
                                        gene_info.transcript_exon_count(transcript_id),
                                        dist_to_tss, dist_to_tts, dist_to_gene_tss, dist_to_gene_tts, subtypes,
                                        all_canonical, indel_count, junctions_with_indels, bite,
                                        ref_cds_start, ref_cds_end, perc_A_downstreamTTS, seq_A_downstream_TTS,
                                        dist_to_cage_peak, within_cage_peak, dist_to_polya_site,
                                        within_polya_site, polyA_motif, polyA_dist]])
        self.output_file.write(l + "\n")

    def __del__(self):
        self.output_file.close()

    def flush(self):
        self.output_file.flush()


class IOSupport:
    canonical_donor_sites = ["GT", "GC", "AT"]
    canonical_acceptor_sites = ["AG", "AC"]
    canonical_donor_sites_rc = ["AC", "GC", "AT"]
    canonical_acceptor_sites_rc = ["CT", "GT"]

    def __init__(self, params):
        self.params = params

    def count_tss_dist(self, read_assignment, transcript_id):
        transcript_start = read_assignment.gene_info.transcript_start(transcript_id)
        read_start = read_assignment.start()
        if read_start < transcript_start:
            return -sum_intervals_to_point(read_assignment.combined_profile.read_exon_profile.read_features, transcript_start)
        else:
            return sum_intervals_to_point(read_assignment.gene_info.all_isoforms_exons[transcript_id], read_start)

    def count_tts_dist(self, read_assignment, transcript_id):
        transcript_end = read_assignment.gene_info.transcript_end(transcript_id)
        read_end = read_assignment.end()
        if read_end > transcript_end:
            return -sum_intervals_from_point(read_assignment.combined_profile.read_exon_profile.read_features, transcript_end)
        else:
            return sum_intervals_from_point(read_assignment.gene_info.all_isoforms_exons[transcript_id], read_end)

    def find_closests_tsts(self, read_assignment):
        gene_info = read_assignment.gene_info
        match = read_assignment.isoform_matches[0]
        gene_id = match.assigned_gene

        dists_to_gene_tss = []
        dists_to_gene_tts = []
        for t in gene_info.db.children(gene_info.db[gene_id], featuretype='transcript', order_by='start'):
            dists_to_gene_tss.append(self.count_tss_dist(read_assignment, t.id))
            dists_to_gene_tts.append(self.count_tts_dist(read_assignment, t.id))
        dist_to_gene_tss = dists_to_gene_tss[argmin([abs(x) for x in dists_to_gene_tss])]
        dist_to_gene_tts = dists_to_gene_tts[argmin([abs(x) for x in dists_to_gene_tts])]
        return dist_to_gene_tss, dist_to_gene_tts

    def find_ref_CDS_region(self, gene_info, transcript_id):
        cds = [c for c in gene_info.db.children(gene_info.db[transcript_id], featuretype='CDS', order_by='start')]
        if len(cds) == 0:
            return -1, -1
        return cds[0].start, cds[-1].end

    def check_all_sites_match_reference(self, read_assignment):
        # FIXME: make a new profile with delta = 0
        if len(read_assignment.combined_profile.read_intron_profile.read_features) == 0:
            return "Unspliced"
        introns_match = all(e == 1 for e in read_assignment.combined_profile.read_intron_profile.read_profile)
        return str(introns_match)

    def check_sites_are_canonical(self, read_introns, gene_info, strand):
        for intron in read_introns:
            if intron not in gene_info.canonical_sites:
                intron_left_pos = intron[0] - gene_info.all_read_region_start
                intron_right_pos = intron[1] - gene_info.all_read_region_start
                left_site = gene_info.reference_region[intron_left_pos:intron_left_pos+2]
                right_site = gene_info.reference_region[intron_right_pos - 1:intron_right_pos + 1]
                if strand == '+':
                    gene_info.canonical_sites[intron] = \
                        (left_site in self.canonical_donor_sites) and (right_site in self.canonical_acceptor_sites)
                else:
                    gene_info.canonical_sites[intron] = \
                        (left_site in self.canonical_acceptor_sites_rc) and (right_site in self.canonical_donor_sites_rc)

            if not gene_info.canonical_sites[intron]:
                return False

        return True

    def check_downstream_polya(self, read_coords, gene_info, strand):
        if strand == '+':
            read_end = read_coords[1] - gene_info.all_read_region_start + 1
            seq = gene_info.reference_region[read_end:read_end + self.params.upstream_region_len]
            a_percentage = float(seq.upper().count('A')) / float(self.params.upstream_region_len)
        else:
            read_start = read_coords[0] - gene_info.all_read_region_start
            seq = gene_info.reference_region[read_start - self.params.upstream_region_len:read_start]
            a_percentage = float(seq.upper().count('T')) / float(self.params.upstream_region_len)
        return seq, a_percentage
