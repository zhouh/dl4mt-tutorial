__author__ = 'jihj'
import codecs
import re

def src_xml(read, write):
    fr = codecs.open(read, 'r', 'utf8')
    fw = codecs.open(write, 'w', 'utf8')

    reg = re.compile('======')
    dic1 = {'&lt;': '<', '&gt;': '>', '&amp;': '&', '&apos;': "'", '&quot;': '"'}
    dic = {'<': '&lt;', '>': '&gt;', '&': '&amp;',  "'": '&apos;', '"': '&quot;'}

    fw.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE mteval SYSTEM \"ftp://jaguar.ncsl.nist.gov/mt/resources/mteval-xml-v1.3.dtd\">\n<mteval>\n")
    fw.write("<srcset setid=\"MT03\" srclang=\"Chinese\">\n")
    fw.write("<doc docid=\"doc1\" genre=\"nw\">\n")
    cnt = 1
    while True:
        line = fr.readline()  # src
        src = line.strip()
        if line == '':
            break
        fr.readline()  # notree
        while True:  # refs
            line = fr.readline()
            if reg.match(line):
                break
        for key in dic.keys():
            cdata = re.compile(key)
            src = cdata.sub(dic[key], src)
        fw.write('<p>\n<seg id="' + str(cnt) + '">' + src + '</seg>\n</p>\n')
        cnt += 1
    fw.write('</doc>\n</srcset>\n</mteval>\n')
    fr.close()
    fw.close()

def ref_xml(read, write):
    fr = codecs.open(read, 'r', 'utf8')
    fw = codecs.open(write, 'w', 'utf8')

    reg = re.compile('======')
    dic = {'<': '&lt;', '>': '&gt;', '&': '&amp;',  "'": '&apos;', '"': '&quot;'}

    fw.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE mteval SYSTEM \"ftp://jaguar.ncsl.nist.gov/mt/resources/mteval-xml-v1.3.dtd\">\n<mteval>\n")

    all_refs = []
    while True:
        line = fr.readline()  # src
        src = line.strip()
        if line == '':
            break
        fr.readline()  # notree
        refs = []
        while True:  # refs
            line = fr.readline()
            if reg.match(line):
                all_refs.append(refs)
                break
            refs.append(line.strip())

    for i in range(4):
        fw.write('<refset setid="MT03" srclang="Chinese" trglang="English" refid="ref' + str(i+1) + '">\n')
        fw.write("<doc docid=\"doc1\" genre=\"nw\">\n")
        for n in range(len(all_refs)):
            r = all_refs[n][i]
            for key in dic.keys():
                cdata = re.compile(key)
                r = cdata.sub(dic[key], r)
            fw.write('<p>\n<seg id="' + str(n+1) + '">' + r + '</seg>\n</p>\n')
        fw.write('</doc>\n</refset>\n')
    fw.write('</mteval>\n')
    fr.close()
    fw.close()

def output_xml(read, write):
    fr = codecs.open(read, 'r', 'utf8')
    fw = codecs.open(write, 'w', 'utf8')
    dic = {'<': '&lt;', '>': '&gt;', '&': '&amp;',  "'": '&apos;', '"': '&quot;'}

    fw.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE mteval SYSTEM \"ftp://jaguar.ncsl.nist.gov/mt/resources/mteval-xml-v1.3.dtd\">\n<mteval>\n")
    fw.write('<tstset setid="MT03" srclang="Chinese" trglang="English" sysid="sample_system">\n')
    fw.write("<doc docid=\"doc1\" genre=\"nw\">\n")

    cnt = 0
    for line in fr:
        for key in dic.keys():
            cdata = re.compile(key)
            line = cdata.sub(dic[key], line)
        fw.write('<p>\n<seg id="' + str(cnt+1) + '">' + line.strip() + '</seg>\n</p>\n')
        cnt += 1
    fw.write('</doc>\n</tstset>\n</mteval>\n')


if __name__ == '__main__':
    read = 'MT06.ce.tree.dev'
    write1 = 'MT06.src.xml'
    write2 = 'MT06.ref.xml'

    readA = 'MT06.trans.en'

    writeA = 'MT06.trans.xml'

    #src_xml(read, write1)
    #ref_xml(read, write2)
    output_xml(readA, writeA)
